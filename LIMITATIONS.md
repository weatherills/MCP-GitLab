# Limitations

What this server doesn't do, what it won't do, and where it behaves in ways you might not expect.
Each entry names the PRD in [`docs/prd/`](docs/prd/) that records it, where there is one. Last
reviewed 2026-09-23.

## Known bugs

- **Host names are matched case-sensitively.** The MCP SDK compares the `Host` header with the
  allowed host names exactly, so `https://Mantle.example.gov/mcp` gets `421 Invalid Host header`
  where `https://mantle.example.gov/mcp` works. Node and Python HTTP clients lowercase host names
  before sending them; curl sends them as typed. Workaround: write host names in lowercase.

No other bugs are known.

## Not yet implemented

Server-wide:

- **Per-caller rate limiting.** It needs state shared across requests and replicas. The proposal
  is to leave request rates and connection caps to a proxy or gateway in front of the server.
  GitLab's own rate limits still apply to each PAT. (PRD-00 §10, §13 Q4)
- **A request size limit.** Neither the server nor the standalone image's Caddy caps a request
  body, and the MCP SDK reads each body whole. If the server is widely reachable, cap bodies in the
  proxy in front. Responses from GitLab are capped (`GITLAB_MAX_RESPONSE_BYTES`,
  `GITLAB_MCP_MAX_FILE_BYTES`).
- **OAuth 2.1.** Authentication is PAT-only; OAuth is a Phase 2 candidate. (PRD-00 §3, §7.3)
- **SSE resumability.** There is no `Last-Event-ID` replay, which needs an event store that a
  stateless server doesn't keep. (PRD-00 §4.2)
- **MCP protocol revision 2026-07-28.** The server is built for 2025-11-25. The SDK also answers
  2026-07-28 requests, but that revision isn't a target yet. (PRD-00 §4.1)
- **MCP resources, prompts, and completions.** The server offers tools only, and its tool list
  doesn't change during a connection.

Per toolset, deferred by each PRD's "Out of Scope (v1)" section unless noted:

- `projects`: transferring a project between namespaces, import and export, badges, custom
  project templates. (PRD-01 §5)
- `repository`: Git LFS objects, repository statistics, submodules. (PRD-02 §5)
- `merge_requests`: draft reviews that post several comments at once; customizing the squash
  commit message. (PRD-03 §5)
- `issues`: creating or editing group-level labels and milestones; time tracking. (PRD-04 §5)
- `pipelines`: pipeline schedules; runner management. (PRD-05 §5)
- `collaboration`: snippets (a Phase 2 candidate, PRD-08 §5); group wikis (PRD-08 open question
  2); setting webhook custom headers and URL variables, which are shown by key but can't be set;
  clearing a membership's expiry date (both in PRD-08's revision note).

## Won't fix

Excluded by design:

- **GitLab Premium and Ultimate features**, such as epics, security and vulnerability scanning,
  compliance frameworks, and release evidence. The target is GitLab Free and Community Edition.
  (PRD-00 §3, PRD-06 §5)
- **Packages, the container registry, and instance administration APIs.** (PRD-00 §3)
- **The stdio transport.** The server is remote-first. (PRD-00 §3)
- **A server-side GitLab token.** `GITLAB_TOKEN` is ignored with a warning: every request must
  carry its caller's own PAT. This is an owner requirement. (PRD-00 §7.2)
- **Other kinds of credential.** Pipeline trigger tokens, CI job tokens (`JOB-TOKEN`), and
  `Authorization` schemes other than `Bearer` aren't read. (PRD-00 §7.2, PRD-05 §5)
- **`approval_password` when approving a merge request.** A user's password must never pass
  through an LLM tool call. (PRD-03 §3)
- **Whole-archive downloads** of a repository ref or a job's artifacts. These are bulk binary
  transfers, not agent operations; artifact files are fetched one at a time. (PRD-02 §5,
  PRD-05 §4)
- **Group and instance administration:** creating groups or changing their settings, SSO and SAML,
  creating or blocking user accounts, and authoring merge request approval rules. (PRD-01 §5,
  PRD-03 §5, PRD-08 §5)
- **Issue boards.** They add nothing beyond labels and milestones. (PRD-04 §5)
- **CI/CD Catalog releases, Advanced Search administration, and search ranking.** These are
  outside repository commands. (PRD-06 §5, PRD-07 §5)

Imposed by GitLab:

- **Premium-only features fail on Free and Community Edition:** `list_approval_rules`, the
  `blocks` and `is_blocked_by` issue link types, and instance- or group-level search of `blobs`,
  `commits`, `wiki_blobs`, and `notes`, which needs Advanced Search. That search failure comes
  back as `advanced_search_unavailable`, pointing to project search. (PRD-03, PRD-04, PRD-07 §4)
- **Some actions depend on the GitLab version:**
  - `list_artifacts` needs 18.8 for its file tree, and falls back to the archive's metadata on
    older versions.
  - Webhook signing tokens need 19.0.
  - `merge` with `auto_merge` also sends the older `merge_when_pipeline_succeeds`, for GitLab
    before 17.11.
  - Since 18.10 an issue's author may delete it.

  (PRD-03, PRD-04, PRD-05, PRD-08)
- **Tags carry no release notes.** GitLab's Tags API has no such field; create a release instead.
  (PRD-01)
- **Issue threads can't be resolved.** GitLab's API resolves only merge request threads. (PRD-04)
- **The wiki page list isn't paginated.** GitLab returns every page at once. (PRD-08)
- **Job logs are downloaded whole** to return their tail, up to `GITLAB_MAX_RESPONSE_BYTES`,
  because GitLab's trace endpoint takes no range. (PRD-05 §4)
- **Changing a webhook's URL drops its secret token and custom headers.** GitLab does this; the
  tool warns when it may have happened. (PRD-08)

## Design decisions

Authentication:

- **The caller's GitLab PAT is the only credential.** It is sent on every request as
  `Authorization: Bearer <PAT>` or `PRIVATE-TOKEN: <PAT>`; `Bearer` wins when both are sent. The
  server uses it only for the GitLab calls made while serving that request, sending it to GitLab
  as `Authorization: Bearer`. It never caches, stores, logs, or reuses it. (PRD-00 §7.2)
- **Forwarding the PAT to GitLab deviates from the MCP authorization spec,** which forbids passing
  a client's token to an upstream API ("confused deputy"). The server follows GitHub's remote MCP
  server and this repository's PAT charter instead. (PRD-00 §7.1)
- **The `/mcp` gate checks only that a token is present** (`401` otherwise); GitLab validates it
  on every call. `initialize` and `tools/list` therefore answer any token, and a tool call with an
  invalid one fails at its first GitLab call with `gitlab_unauthorized`. (PRD-00 §4.3, §13 Q4)
- **Scope-aware tool visibility is a convenience, not a security boundary.** `tools/list` reads
  the token's scopes (`GET /personal_access_tokens/self`) and hides what the token can't use: a
  `read_api` token sees read actions only, and a `read_user` token sees only `gitlab_users`. If the
  lookup fails, as it does for an invalid token, every tool is listed. Tool calls aren't filtered
  by scope; GitLab refuses them with `403`. (PRD-00 §7.2)
- **Toolset selection and read-only mode are enforced on tool calls, not only in the list.** The
  per-request headers (`X-MCP-Toolsets`, `X-MCP-Readonly`) can only narrow what the deployment
  allows. (PRD-00 §6)
- **Redirects from GitLab are refused**, except on downloads (job logs, artifact files). There, a
  hop to another origin is made without the PAT. (PRD-00 §7.2)

Transport:

- **Stateless by default.** No `MCP-Session-Id` is issued, any replica can serve any request,
  `initialize` isn't required before a tool call, and `GET /mcp` returns `405`. Stateful mode
  (`MCP_STATELESS_HTTP=false`) needs sticky routing across replicas, and its sessions never hold a
  PAT. (PRD-00 §5)
- **Responses are SSE streams** unless `MCP_JSON_RESPONSE=true`. (PRD-00 §4.2)
- **`MCP-Protocol-Version`:** an unsupported value gets `400`. A request without the header is
  treated as 2025-03-26, as the MCP spec says servers should for backward compatibility.
  (PRD-00 §4.2)
- **Host and Origin are checked on every bind address** (`421` and `403` on a mismatch).
  (PRD-00 §4.3)
- **Plaintext HTTP only on loopback.** Elsewhere the server needs native TLS,
  `MCP_TLS_TERMINATED_UPSTREAM=true` behind a TLS proxy, or `--insecure-dev`. (PRD-00 §9)

GitLab calls:

- **A `POST` that fails with a `5xx` isn't retried.** It may already have been applied (a
  duplicate commit, say), so it comes back as a retryable error for the caller to check. `429` is
  retried for any method; a `Retry-After` longer than 30 s comes back as a retryable error with
  `retry_after_seconds` instead of being slept through. (PRD-00 §10)
- **Lists are paginated** (`page`, `per_page`: default 20, maximum 100) and never fetched whole.
  (PRD-00 §10)
- **Size caps:** 10 MiB per GitLab response (`GITLAB_MAX_RESPONSE_BYTES`) and 1 MiB per file
  (`GITLAB_MCP_MAX_FILE_BYTES`). A larger file gets `payload_too_large`, never a silently
  truncated file. (PRD-00 §10, PRD-02 §4)
- **Diffs:** commit, compare, and merge request diffs return a changed-files summary, with a
  file's diff text on request. (PRD-02 §4, PRD-03 §4)
- **TLS verification to GitLab stays on.** `GITLAB_SKIP_TLS_VERIFY` is refused against gitlab.com,
  and `GITLAB_CA_BUNDLE` replaces the system CAs rather than adding to them. (PRD-00 §7.4)

Tools:

- **One coarse tool per domain,** taking an `action` argument: 22 tools rather than one per GitLab
  endpoint. (PRD-00 §6)
- **`confirm: true` is required by** `gitlab_projects.delete`, `gitlab_branches.delete` and
  `delete_merged`, `gitlab_merge_requests.merge`, `gitlab_issues.delete`,
  `gitlab_pipelines.delete`, and `gitlab_members.update` and `remove`. Deleting a release doesn't
  need it, since the tag stays. (PRD-01 §4, PRD-06 §4)
- **File content is text,** or base64 when it isn't UTF-8. `create_directory` commits
  `<dir>/.gitkeep`, since Git stores no empty directories. A file `update` or `delete` needs
  `last_commit_id`, so a concurrent edit surfaces as GitLab's conflict error. (PRD-02 §4)
- **`gitlab_issues.list` defaults to open issues;** GitLab's own default is every state. (PRD-04)
- **A refused merge** comes back as `merge_blocked` or `merge_pending`, with GitLab's
  `detailed_merge_status` and a next step. (PRD-03)
- **Job logs** return the last 500 lines by default, cleaned of color codes; `offset` pages
  through a log and `full: true` returns all of it. (PRD-05)
- **CI/CD variable values are hidden in every response,** unless `get` is called with
  `reveal_value: true`. `update` without `value` keeps the current value without passing it
  through the model. (PRD-05 §4)
- **Webhook secret and signing tokens are write-only;** custom headers and URL variables are shown
  by key only. (PRD-08 §4)
- **Wiki `update` keeps the page's format:** it reads the format first, because GitLab resets an
  omitted format to markdown. (PRD-08)
- **Advanced Search availability is checked per call,** not probed at startup, so the server stays
  stateless. (PRD-07)
- **Members:** access levels are accepted by name or number. `update` and `remove` act on direct
  members only. Removing yourself needs only `confirm: true` (PRD-08 open question 1).

Logging:

- **Logs never hold argument values, the PAT, or GitLab response bodies.** They record the tool,
  action, argument names, outcome, and latency of each call, and the status of each GitLab call,
  and a redaction pass also scrubs anything shaped like a token. (PRD-00 §11)

## Standalone image and deployment

- **Caddy and the MCP server share one container,** run by a Python entrypoint with no init
  system. On stop it waits up to 8 s for in-flight requests (Caddy's own grace period is 5 s), then
  kills what's left. (PRD-00 §9)
- **One host name per deployment.** Caddy serves `MCP_PUBLIC_HOST` only; other names and bare IP
  addresses get `421`. The server's `MCP_ALLOWED_HOSTS` is derived from it, and a value you set is
  ignored.
- **A certificate you provide** must cover `MCP_PUBLIC_HOST` and be readable by uid 10001. Caddy
  neither renews nor reloads it: replace the files and restart the container. The health check
  doesn't look at the certificate's expiry.
- **The local CA,** used when no certificate is provided, has a root valid for about 10 years,
  kept in the `/data` volume. If the volume is lost, clients must trust a new root.
- **With the local CA, the certificate arrives just after the port opens.** Caddy issues it a
  moment (about 50 ms here) after it starts listening, and a client that connects in that window
  gets a TLS `internal_error` alert. The health check's start period covers it.
- **Caddy's logs never include request headers,** because its error log redacts `Authorization`
  but not `PRIVATE-TOKEN`. There is no access log either. This trades away some debugging detail.
- **HTTP/3, OCSP stapling, and Caddy's admin API are off:** there's no UDP port to publish, no
  outbound call except to GitLab, and nothing listening on port 2019.
- **The container listens on 8443,** since it runs as a non-root user; `deploy/compose.yaml`
  publishes it on 443.
- **Responses carry a `Server: Caddy` header.**
- **Only the standalone image is published,** for linux/amd64 and linux/arm64. Build the
  server-only image with `docker build --target server .`.
- **The published image and `deploy/compose.yaml` preset the NASA deployment**
  (`git.smce.nasa.gov`, `mantle.scipai.sandbox.sciencecloud.nasa.gov`). This repository is
  public, so those host names are too.
- **The package on GHCR (GitHub Container Registry) is private** until an organization owner
  changes its visibility. Until then, pulling it needs a login.

## Open questions for the owner

Answering these differently would change behavior; each PRD's Open Questions section has the
detail.

- Sign off on protocol revision 2025-11-25. (PRD-00 §13 Q1)
- Leave rate limiting to the proxy in front? (PRD-00 §13 Q4)
- Make the riskiest actions opt-in rather than default: deleting a project (PRD-01 Q1), merging
  (PRD-03 Q1), deleting an issue (PRD-04 Q1), and revealing a CI/CD variable's value (PRD-05 Q2).
- Is 1 MiB the right file-size cap, and should `batch_commit` be the only way to write files?
  (PRD-02 Q1, Q2)
- Is 500 lines the right default job-log tail? (PRD-05 Q1)
- Block removing your own membership outright, and add group wikis? (PRD-08 Q1, Q2)
