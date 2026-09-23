# CLAUDE.md

Guidance for whoever (human or AI) implements this repo next.

## What this is

An HTTPS GitLab MCP (Model Context Protocol) server, using the **Streamable HTTP** transport, that
exposes GitLab repository commands as MCP tools. Targets non-enterprise GitLab (gitlab.com and
self-hosted GitLab CE/EE, Community-Edition feature parity only), authenticated with GitLab
Personal Access Tokens (PATs).

## Current state

- **Built:** the framework (transport, auth, GitLab client, tool framework) per PRD-00, plus the
  toolsets for PRD-01 to PRD-08 (see the table), and the standalone Docker image (Caddy for TLS in
  front of the server, PRD-00 §9) that CI publishes to GHCR, with a Compose bundle in `deploy/`.
  What remains is the owner's review of the PRDs and their open questions.
- The PRDs in `docs/prd/` are the spec ("true north"). Every PRD still reads `Status: Draft`: they
  were merged before formal review, at the owner's direction, and the owner is reviewing them now.
  Each implemented PRD carries a **Revised 2026-09-22** note listing what implementation changed.
  The same PRDs live in the review doc at
  https://claude.ai/code/artifact/5f511063-0ef0-4575-bdec-7300ece02c5a — keep the two in sync.

| PRD | Toolset | Domain | State |
|---|---|---|---|
| PRD-00 | — | Architecture, transport, auth (read first) | Built |
| PRD-01 | `projects` | Projects, branches, tags | Built |
| PRD-02 | `repository` | File tree, files, directories, commits, diffs | Built |
| PRD-03 | `merge_requests` | MRs, discussions, approvals, merge | Built |
| PRD-04 | `issues` | Issues, labels, milestones | Built |
| PRD-05 | `pipelines` | CI/CD pipelines, jobs, variables | Built |
| PRD-06 | `releases` | Releases, release links | Built |
| PRD-07 | `search` | Global/group/project search | Built |
| PRD-08 | `collaboration` | Members, users, webhooks, wikis | Built |

## Owner requirements (non-negotiable)

1. **Shared server, one PAT per request.** Every request carries its caller's own PAT, and that PAT
   is used only for the GitLab calls made while serving that request — never cached, never stored
   in an MCP session, never used for any other request. There is no server-side token
   (`GITLAB_TOKEN` is ignored with a warning). `tests/transport/test_isolation.py` and
   `tests/transport/test_write_workflow.py` prove this with concurrent callers; they must keep
   passing.
2. **Read-write.** The server creates repositories, branches, directories, and files, not just
   reads them. Read-only is opt-in (`GITLAB_MCP_READ_ONLY` or the `X-MCP-Readonly` header).

## Architecture

Ports and adapters, stateless by default. Dependencies point inward only:

```
transport/  (MCP + HTTP adapter)  ─┐
toolsets/   (GitLab domains)       ├─→ tools/ (tool framework) ─→ core/
gitlab/     (GitLab REST adapter) ─┘                              ↑
app.py      composition root: wires everything; nothing imports it
```

```
src/mcp_gitlab/
  __main__.py       # `mcp-gitlab` entrypoint: settings, TLS policy, uvicorn
  standalone.py     # the standalone image's entrypoint: runs Caddy and the server, health check
  app.py            # create_app(): registry → GitLab client → dispatcher → MCP server → ASGI app
  config.py         # Settings (PRD-00 §8) and the startup safety checks (§4.3, §7.4, §9)
  core/             # errors (ToolError hierarchy), per-request context + PAT extraction, JSON logs
  gitlab/           # GitLabClient (shared pool, retries, size caps), GitLabSession (one PAT),
                    #   pagination, path encoding, token-scope lookup
  tools/            # Action/Tool/Toolset model, JSON schema builder, registry (toolset and
                    #   read-only filtering), dispatcher (validation, confirm, errors, logging)
  transport/        # MCP lowlevel server (tools/list, tools/call) and the Starlette app:
                    #   /mcp behind the 401 PAT gate, /healthz
  toolsets/
    __init__.py     # TOOLSETS — register each new toolset here
    common.py       # shared param types (ProjectRef, NamespaceRef, Ref, access levels), query(),
                    #   with_hint() to add advice to a GitLab error
    content.py      # bytes to text-or-base64, and the file-too-large error
    diffs.py        # changed-file summaries (PRD-00 §10 large-payload discipline)
    threads.py      # discussions and notes, shared by merge requests and issues
    time_tracking.py  # estimates and time spent, shared by merge requests and issues
    projects/       # PRD-01: gitlab_projects, gitlab_branches, gitlab_tags
    repository/     # PRD-02: gitlab_repository_tree, gitlab_files, gitlab_commits
    merge_requests/ # PRD-03: gitlab_merge_requests, gitlab_mr_reviews
    issues/         # PRD-04: gitlab_issues, gitlab_issue_notes, gitlab_labels, gitlab_milestones
    pipelines/      # PRD-05: gitlab_pipelines, gitlab_jobs, gitlab_ci_variables
    releases/       # PRD-06: gitlab_releases, gitlab_release_links
    search/         # PRD-07: gitlab_search
    collaboration/  # PRD-08: gitlab_members, gitlab_users, gitlab_wikis, gitlab_webhooks
tests/              # mirrors src/; toolsets/wire.py drives actions and asserts the GitLab request
deploy/             # Caddyfile (built into the standalone image) and compose.yaml (the bundle)
```

How one tool call flows: `transport/http.py` rejects a request without a PAT (`401`) →
`transport/mcp_server.py` builds a `RequestContext` from **that request's** headers →
`tools/dispatcher.py` resolves the tool and action, checks `confirm`, validates the arguments →
the handler runs with `ctx.gitlab`, a `GitLabSession` bound to that request's PAT → the result or a
`ToolError` goes back as structured content.

## Adding a toolset

1. Create `src/mcp_gitlab/toolsets/<toolset>/`, one module per tool, following
   `toolsets/repository/tree.py` (smallest) or `toolsets/projects/branches.py` (typical).
2. Per action, declare a params model (subclass `ActionParams`, or `PageParams` for lists; field
   descriptions become the tool schema) and an `async def handler(params, ctx: ActionContext)`.
   Call GitLab only through `ctx.gitlab` (`get`, `get_page`, `get_bytes`, `post`, `put`, `delete`),
   and build paths with `project_path()`, `group_path()`, and `encode_segment()`
   (`encode_wildcard_path()` for routes that take literal slashes, such as artifact paths). Pass
   `follow_redirects=True` to `get_bytes` only for downloads GitLab may hand off to object
   storage; the PAT never follows a redirect to another origin.
3. Declare `Action(name, description, Params, handler, Access.READ | Access.WRITE,
   destructive=True?)`, group actions into a `Tool`, and the tools into a `Toolset` in the package's
   `__init__.py`. Add the toolset to `TOOLSETS` in `toolsets/__init__.py`.
4. Add `tests/toolsets/test_<toolset>.py` with a module-level `CASES` list: at least one wire
   `Case` per action (method, path, query, body), then tests for any logic of your own. Two
   suites pick `CASES` up automatically: `tests/toolsets/test_coverage.py` fails if any registered
   action has no case, and `tests/transport/test_every_tool.py` replays each tool's cases through
   the real MCP client, validating the arguments against the schema `tools/list` advertises.

Declarations are checked when they're built and again when the registry loads them: invalid or
duplicate names, `destructive` on a read action, and one parameter name with different types
across a tool's actions all fail at startup, not on first call. A parameter may be optional for
one action and required for another; reuse one `Annotated` type so its description fits every
action, since the tool schema shows one description per parameter.

## Conventions

- Python ≥3.10, `src/` layout, package name `mcp_gitlab`.
- **Git: work directly on `main`.** Don't create branches, local or remote — the owner's
  instruction. Commit to `main` and push it; CI runs on every push to `main`.
- Lint/format: `ruff` (`ruff check .`, `ruff format .`). Types: `mypy --strict` (`mypy src`).
  Tests: `pytest`. CI runs all three on Python 3.10 and 3.12 (with the image's Caddy installed,
  so the standalone tests run), builds both Docker images and waits for them to report healthy,
  runs the Compose bundle in both TLS modes, and then, on `main`, publishes the standalone image
  to GHCR — keep them passing.
- Per PRD-00 §6: one coarse tool per domain with an `action` discriminator
  (`gitlab_branches(action="list"|"create"|...)`), not one MCP tool per GitLab REST endpoint.
- Destructive/high-impact actions (each PRD's tables mark them) are declared `destructive=True`,
  which makes the dispatcher require `confirm: true`. Don't add this to ordinary reads or writes.
- Handlers return plain data: a dict/list from GitLab, a `Page` for lists, or `None` for success
  with no body. Raise a `ToolError` subclass (`core/errors.py`) for caller mistakes; GitLab HTTP
  errors are mapped for you.
- Secrets (the PAT, CI/CD variable values, webhook tokens) are never logged and never echoed back
  unless the specific PRD says otherwise (e.g. CI/CD variable `get` with `reveal_value: true`,
  PRD-05 §3). Logs record argument names, never values.
- List actions take `page`/`per_page` (`PageParams`) and return pagination metadata (PRD-00 §10)
  — never fetch-all internally.
- Never call `httpx` from a toolset, and never keep per-caller state in module globals or on the
  client: the only per-request state is the `RequestContext` and its `GitLabSession`.

## Decisions made during implementation

Recorded in the PRDs' revision notes; summarized here so they aren't re-litigated by accident.
[`LIMITATIONS.md`](LIMITATIONS.md) has the full list, with known bugs and what isn't built or
won't be; keep it current when you add a limitation or make a decision.

- **MCP SDK:** `mcp>=2.2,<3`, using the lowlevel `mcp.server.Server`. SDK 2.2 serves protocol
  revision 2025-11-25 (PRD-00's target) and also answers 2026-07-28 requests on the same endpoint.
- **Stateless by default** (`MCP_STATELESS_HTTP=true`); stateful sessions are optional and never
  hold a credential. In stateless mode `GET /mcp` returns `405`, since there is nothing to push.
- **No retry of `POST` on `5xx`:** it may already have been applied (duplicate commits). `429` is
  retried for any method.
- **File content is text by default**, base64 only for non-UTF-8 content (PRD-02 §4).
- **`create_directory`** commits `<dir>/.gitkeep`, since Git has no empty directories (PRD-02).
- **Tags carry no release notes** — the Tags API has no such field (PRD-01).
- **Wiki `update` keeps the page's format:** GitLab resets an omitted `format` to markdown, so the
  tool reads the page's current format first (PRD-08).
- **Standalone image:** Caddy terminates TLS in the same container (the operator's certificate
  from `/certs`, or one from Caddy's local CA) and proxies to the server on loopback;
  `mcp_gitlab.standalone` supervises both, with no init system. Caddy's logs leave out request
  headers: it logs each request it fails with a 5xx, headers included, and redacts
  `Authorization` but not `PRIVATE-TOKEN` (PRD-00 §9).
- **Not built:** PRD-00 §10's per-caller outbound rate limit (needs shared state; PRD-00 §13 Q4).

## Running things

```
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check . && mypy src && pytest
mcp-gitlab                 # http://127.0.0.1:8080/mcp; --insecure-dev allows plaintext off loopback
cd deploy && docker compose up -d   # the standalone image: https://$MCP_PUBLIC_HOST/mcp
```

No `.env` is needed for the test suite. For manual runs, copy `.env.example` to `.env`. Clients send
`Authorization: Bearer <PAT>` on every request.
