# CLAUDE.md

Guidance for whoever (human or AI) implements this repo next.

## What this is

An HTTPS GitLab MCP (Model Context Protocol) server, using the **Streamable HTTP** transport, that
exposes GitLab repository commands as MCP tools. Targets non-enterprise GitLab (gitlab.com and
self-hosted GitLab CE/EE, Community-Edition feature parity only), authenticated with GitLab
Personal Access Tokens (PATs).

## Current state

**Specced, not yet implemented.** Nine PRDs in `docs/prd/` define the full system; no server code
exists yet beyond project scaffolding (packaging, config, CI, tests for the config module). Every
PRD file's own header currently reads `Status: Draft` — they were merged to `main` before formal
per-PRD review sign-off, at the repo owner's explicit direction, so treat their content as the
working spec but check for updates before relying on any single detail long-term.

Read `docs/prd/PRD-00-architecture.md` first — it defines transport, auth, tool organization, and
the shared conventions (pagination, error handling, retries) every other PRD depends on. Then
`docs/prd/PRD-01-projects.md` through `PRD-08-collaboration.md`, one per GitLab command domain.

| PRD | Toolset | Domain |
|---|---|---|
| PRD-00 | — | Architecture, transport, auth (read first) |
| PRD-01 | `projects` | Projects, branches, tags |
| PRD-02 | `repository` | File tree, files, commits, diffs |
| PRD-03 | `merge_requests` | MRs, discussions, approvals, merge |
| PRD-04 | `issues` | Issues, labels, milestones |
| PRD-05 | `pipelines` | CI/CD pipelines, jobs, variables |
| PRD-06 | `releases` | Releases, release links |
| PRD-07 | `search` | Global/group/project search |
| PRD-08 | `collaboration` | Members, users, webhooks, wikis |

## Before you write `server.py`

**Verify the MCP Python SDK's current API before wiring up the transport — do not assume the
latest release matches PRD-00's target.** While preparing this repo, fetching the SDK's current
README showed a `MCPServer`/`@mcp.tool()`/`mcp run --transport streamable-http` surface that looks
like a newer "v2" SDK line; earlier research for PRD-00 found an older `FastMCP` line (manual ASGI
mounting, `streamable_http_path`/`stateless_http`/`session_idle_timeout` options) associated with
protocol revision 2025-11-25, while the newest SDK releases appear to be moving toward protocol
revision 2026-07-28 — which **removes MCP sessions entirely**, a breaking change from what PRD-00
§4 specifies and what this repo's `config.py` (`MCP_SESSION_IDLE_TIMEOUT`, `MCP_MAX_SESSIONS`)
already assumes. Concretely, before writing any transport code:

1. Check the installed/target `mcp` package version against which protocol revision it implements.
2. If it's already on 2026-07-28 semantics, pin to an earlier release that still implements
   2025-11-25 session-based Streamable HTTP, **or** take this back to a PRD-00 revision — don't
   silently build against whichever the dependency resolver happens to pick.
3. Only then write `src/mcp_gitlab/server.py`.

This isn't optional busywork: it decides whether `Settings.mcp_session_idle_timeout` and
`Settings.mcp_max_sessions` are meaningful at all.

## Layout

```
src/mcp_gitlab/
  __init__.py       # exists
  py.typed          # exists (PEP 561 marker)
  config.py         # exists — Settings, from PRD-00 §8
  server.py         # NOT YET WRITTEN — entrypoint; see "Before you write server.py" above
  gitlab_client.py  # NOT YET WRITTEN — shared HTTP client: PAT propagation (PRD-00 §7),
                    #   retry/backoff/pagination (PRD-00 §10). Every toolset module below
                    #   should depend on this rather than calling httpx directly.
  toolsets/
    projects.py         # NOT YET WRITTEN — PRD-01
    repository.py       # NOT YET WRITTEN — PRD-02
    merge_requests.py   # NOT YET WRITTEN — PRD-03
    issues.py           # NOT YET WRITTEN — PRD-04
    pipelines.py        # NOT YET WRITTEN — PRD-05
    releases.py         # NOT YET WRITTEN — PRD-06
    search.py           # NOT YET WRITTEN — PRD-07
    collaboration.py    # NOT YET WRITTEN — PRD-08
tests/
  __init__.py
  test_config.py    # exists
  # one test module per toolset, mirroring src/mcp_gitlab/toolsets/, as each is built
```

Suggested build order: `server.py` (transport skeleton, zero tools, per the verification step
above) → `gitlab_client.py` → `toolsets/projects.py` (everything else's dependency for
`project_id` resolution) → the remaining toolsets in any order → `search.py` last, since it's most
useful once the things it links back into (PRD-01/02/03/04) already exist.

## Conventions

- Python ≥3.10, `src/` layout, package name `mcp_gitlab`.
- Lint/format: `ruff` (`ruff check .`). Types: `mypy --strict` (`mypy src`). Tests: `pytest`.
  All three currently pass on `main` — keep them passing.
- Per PRD-00 §6: prefer one coarse tool per domain with an `action` discriminator parameter
  (`gitlab_branches(action="list"|"create"|...)`) over one MCP tool per GitLab REST endpoint.
- Destructive/high-impact actions (project/branch/issue delete, MR merge, member remove — each
  PRD's tables mark these) require an explicit `confirm: true` argument; don't add this ceremony
  to ordinary reads or routine writes.
- Secrets (GitLab PAT, CI/CD variable values, webhook tokens) are never logged and never echoed
  back in a tool response unless the specific PRD says otherwise (e.g. CI/CD variable `get` with
  `reveal_value: true`, PRD-05 §3).
- List-style tools take `page`/`per_page` and return pagination metadata (PRD-00 §10) — never
  silently fetch-all internally.

## Running things

```
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
mypy src
pytest
```

No `.env` is required to run the test suite as it stands (config tests set env vars themselves via
`monkeypatch`). Copy `.env.example` to `.env` for local manual runs once `server.py` exists.
