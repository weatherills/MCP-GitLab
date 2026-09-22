# PRD-00: Architecture, Transport & Auth

**Status:** Draft · **Owner:** brian@weatherills.com · **Depends on:** none (this PRD is a dependency of PRD-01 through PRD-08)

> **Revised 2026-09-22 (still Draft).** The owner set two hard requirements: the server is a
> **shared** resource, so every request carries its caller's own PAT, used for that request and no
> other; and it is **read-write**, able to create repositories, branches, directories, and files.
> §2, §4, §5, §6, §7.2, §8–§11, and §13 are updated to match; the server-side `GITLAB_TOKEN`
> fallback is removed.

## 1. Overview

This PRD defines the foundation every other PRD builds on: the HTTP Streaming transport, session
handling, GitLab connection/authentication, tool organization, configuration, and cross-cutting
non-functional requirements (error handling, pagination, security, observability) for the
`weatherills/mcp-gitlab` MCP (Model Context Protocol) server. PRD-01 through PRD-08 each add a set
of GitLab-command tools on top of what this PRD establishes; none of them should re-decide
transport, auth, or error-handling conventions — they inherit them from here.

No official reference implementation exists to copy: the original `modelcontextprotocol/servers`
repo shipped a 9-tool GitLab server, but it has been archived with no successor
([servers-archived/src/gitlab](https://github.com/modelcontextprotocol/servers-archived/tree/main/src/gitlab)).
The design below is instead grounded directly in the MCP specification and in the architecture of
mature, still-maintained servers — chiefly `github/github-mcp-server`, the largest and
best-documented remote MCP server in general use today, plus a survey of ~7 independent GitLab MCP
servers (see Sources).

## 2. Goals

- Implement the MCP **Streamable HTTP** transport as a remote, multi-user, multi-tenant server (not
  a single-user local stdio tool), reachable over HTTPS.
- Support both **gitlab.com and self-hosted GitLab** instances, GitLab Community Edition feature
  parity only (see Non-Goals) — matching the repo's stated scope of "non-enterprise GitLab servers."
- Authenticate to GitLab using **Personal Access Tokens (PATs)**, per the repo's charter. The server
  is a **shared resource**: every request carries its caller's own PAT, and that PAT is used only for
  the GitLab calls made on behalf of that request — never cached, never attached to a session, never
  used for any other request (§7.2). There is no server-side token.
- Be **read-write**, not read-only: callers can create projects (repositories), branches,
  directories, and files, as well as read them. Read-only is an opt-in restriction (§6).
- Keep the tool surface navigable as GitLab's API is large: organize tools into **toolsets** by
  domain (one toolset per functional PRD) that can be selected per deployment or per connection.
- Establish shared conventions — pagination, error shapes, retry/backoff, logging — that every
  functional PRD reuses instead of inventing its own.

## 3. Non-Goals (v1)

- **No OAuth 2.1 / Dynamic Client Registration flow.** The MCP Authorization spec
  ([2025-06-18/basic/authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization))
  defines a full OAuth 2.1 resource-server flow (RFC 9728 Protected Resource Metadata, RFC 8414
  Authorization Server Metadata, RFC 7591 Dynamic Client Registration, PKCE, RFC 8707 resource
  indicators). This is the spec-preferred path and is noted as a Phase 2 candidate (see §7.3), but
  the repo's charter calls for PAT-based auth, and GitHub's own remote server treats PAT as an
  equally first-class, host-agnostic fallback — so v1 ships PAT-only.
- **No GitLab Enterprise/Ultimate-tier features** — e.g. epics/work items (Premium+), security &
  vulnerability scanning APIs, compliance frameworks. These are consistently treated as
  out-of-scope or long-tail across every surveyed community server and require license tiers this
  repo isn't targeting.
- **No stdio transport.** Some community servers support stdio for local single-user use; this
  server is remote-first, so stdio is left out unless a later PRD asks for it explicitly.
- **No full GitLab API parity.** GitLab's own resource index lists 100+ resource groups (including
  8+ language-specific package registries, container-registry protection, Sidekiq admin,
  instance-level admin). Packages, container registry, and instance/admin APIs are explicitly out
  of scope for every PRD in this set.

## 4. Transport: Streamable HTTP

### 4.1 Protocol revision — recommendation implemented, sign-off still open

The MCP spec has moved through several revisions since introducing Streamable HTTP, and they are
not all compatible:

| Revision | What changed | Session model |
|---|---|---|
| 2025-03-26 | Introduced Streamable HTTP (single `POST`/`GET` endpoint), replacing the older two-endpoint HTTP+SSE transport | `Mcp-Session-Id` header, optional |
| 2025-06-18 | Transport mechanics unchanged; OAuth 2.1 Authorization spec matured | Same |
| 2025-11-25 | Header renamed to `MCP-Session-Id`; `403` on bad `Origin` made mandatory; added a required `MCP-Protocol-Version` header on every HTTP request; added SSE reconnect/retry semantics | Same model, stricter |
| 2026-07-28 | **Breaking rewrite**: removes protocol-level sessions and `Mcp-Session-Id` entirely, drops the `initialize` handshake in favor of per-request `_meta`, replaces the GET/SSE stream with a `subscriptions/listen` endpoint, drops `Last-Event-ID`/resumability. HTTP+SSE formally marked Deprecated. | No sessions |

**Recommendation:** target **2025-11-25** as the baseline (current widely-deployed revision; what
today's clients, including Claude Code/Desktop, and GitHub's own server implement), track
2026-07-28 as a future direction but do not build against it yet — its removal of sessions is a
different architecture, not an incremental change, and it is barely two months old as of this
writing. This recommendation is the assumption flagged in this doc's review comment; the rest of
this PRD assumes it.

**Implementation status:** built against 2025-11-25 as recommended. The MCP Python SDK the server
uses (`mcp` 2.2.x) also answers 2026-07-28 requests on the same endpoint, and because the server
keeps no per-connection state by default (§5), nothing it does depends on sessions — so a later move
to 2026-07-28 costs little. Formal sign-off is still open (§13 Q1).

### 4.2 Endpoint behavior (2025-11-25)

- Single endpoint, `POST /mcp` and `GET /mcp` on the same route.
- **POST** (client → server): request must send `Accept: application/json, text/event-stream`. A
  request-free body (only notifications/responses) gets `202 Accepted`. A request gets back either
  `Content-Type: application/json` (one JSON-RPC response) or `Content-Type: text/event-stream`
  (server may stream related requests/notifications before the final response). The server must
  support emitting either; the client must support consuming either.
- **GET** (server → client): opens a standalone SSE stream for async server-initiated messages.
  Server returns `text/event-stream` or `405` if it doesn't support server push outside a request.
  As built, stateless mode (the default, §5) answers `405` with `Allow: POST`, since there is no
  session to push to; stateful mode opens the stream.
- **Sessions (stateful mode only, off by default — §5):** server returns `MCP-Session-Id` on
  `InitializeResult`; client echoes it on every subsequent request; server responds `400` if a
  session-bearing request is missing it, `404` if the session has been terminated (forcing the
  client to re-`initialize`). Client should send `DELETE` with the session header to end a session
  explicitly.
- **`MCP-Protocol-Version` header** is required on every request from 2025-11-25 onward; the server
  rejects mismatched/unsupported versions with a clear error rather than guessing.
- **Resumability:** SSE events may carry a per-stream `id`; on disconnect the client reconnects via
  `GET` with `Last-Event-ID`, and the server replays only that stream's missed messages. **Not
  provided in v1:** replay needs an event store, which a stateless server doesn't keep.

### 4.3 Security requirements (spec-mandated, not optional)

- **Validate the `Origin` header** on every request to prevent DNS-rebinding attacks; reject with
  `403` on mismatch (mandatory since 2025-11-25). The `Host` header is checked too (`421` on
  mismatch). Both checks stay on for every bind address, driven by `MCP_ALLOWED_ORIGINS` and
  `MCP_ALLOWED_HOSTS` (§8), not only for loopback.
- **Do not bind to `0.0.0.0`** for any local/dev mode; bind to `127.0.0.1`. The production
  deployment target is behind HTTPS termination (see §9), so this mainly matters for local dev.
  Given this repo's name and README explicitly call out **HTTPS**, TLS termination is a first-class
  requirement, not an afterthought — see §9.
- **Require authentication on all connections** — no anonymous tool calls, even for read-only
  tools, since a caller's GitLab PAT determines exactly what they can see (§7). Enforced before any
  MCP processing: a `/mcp` request without a PAT gets `401` with `WWW-Authenticate: Bearer`. The
  gate checks that a PAT is present; GitLab validates it on every call.

## 5. Session Management

- **Stateless by default** (`MCP_STATELESS_HTTP=true`): every HTTP request is self-contained. No
  `MCP-Session-Id` is issued and nothing about a caller is kept between requests, so any replica can
  serve any request — horizontal scaling needs no sticky routing and no shared store.
- **Stateful mode** (`MCP_STATELESS_HTTP=false`) remains available for clients that want the
  standalone server-push stream: one `MCP-Session-Id` maps to one initialized MCP session holding
  the negotiated protocol capabilities. `MCP_SESSION_IDLE_TIMEOUT` and `MCP_MAX_SESSIONS` (§8) bound
  its memory use on a shared host and apply only in this mode. Across replicas it needs sticky
  routing.
- **In neither mode does a session hold a credential.** The caller's PAT is read from each HTTP
  request and used only for the GitLab calls that request triggers (§7.2); every later request in
  the same session must bring its own PAT or is rejected with `401`.

## 6. Tool Organization (toolsets)

GitLab's API surface is too large to expose as one tool per endpoint — every mature server surveyed
converges on some form of grouping. This repo follows **GitHub's `github-mcp-server` pattern**
directly, since it's the most-deployed precedent at this scale (96 tools across ~22 toolsets):

- Each functional PRD (PRD-01 … PRD-08) defines exactly one **toolset**, named after its domain
  (e.g. `repository`, `merge_requests`, `issues`, `pipelines`, `releases`, `search`,
  `collaboration`).
- **Within** a toolset, prefer coarser tools with an action/method discriminator parameter over one
  tool per REST endpoint, e.g. a single `gitlab_branches` tool taking
  `{"action": "list"|"get"|"create"|"delete"|"protect", ...}` rather than five separate tools. This
  is the specific mechanism GitHub uses to cover its entire API surface in ~96 tools instead of
  several hundred, and each functional PRD's tool list should be read in that spirit — a proposed
  tool count, not a mandate to declare that many separate MCP tool schemas.
- Toolset selection is configurable two ways, mirroring GitHub's remote server:
  - **Env var** at deploy time: `GITLAB_MCP_TOOLSETS=repository,merge_requests,issues` (default: a
    sensible core set — see §8).
  - **Per-request header** on the remote HTTP server: `X-MCP-Toolsets`, so one deployment can
    serve different tool subsets to different clients without a redeploy. The header selects
    within the deployment's allow-list and can never enable a toolset the deployment excludes;
    `all` selects everything the deployment allows.
- A `read_only` mode (`GITLAB_MCP_READ_ONLY`, or the `X-MCP-Readonly: true` header per request)
  hides and refuses every mutating action across every toolset at once. It is **off by default** —
  the server is read-write (§2) — and the header can only tighten the deployment's setting, never
  loosen it.

## 7. Authentication & GitLab Connection

### 7.1 Why PAT, and why per-request

The MCP Authorization spec is OAuth-only and explicitly requires that servers not pass a
client-presented token through to an upstream API unmodified ("confused deputy" protection —
[2025-06-18/basic/authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)).
This repo makes a deliberate, documented exception to that guidance for v1, following GitHub's own
precedent: GitHub's remote server accepts a raw PAT via `Authorization: Bearer` and forwards it to
the GitHub API, describing OAuth as "recommended" but PAT as something "any host should support" —
because it needs no per-host app registration and works unattended (CI, scripts). Given this repo's
charter is explicitly PAT-based, v1 adopts the same trade-off. This is a known, accepted deviation
from the spec's strict guidance, not an oversight.

### 7.2 Mechanism

- The client sends a GitLab PAT on **every** HTTP request to `/mcp`, not just on `initialize`, as
  **either** `Authorization: Bearer <PAT>` or GitLab's own `PRIVATE-TOKEN: <PAT>` header. A request
  without one is rejected with `401` before any MCP processing. The server reads tokens from no other
  source.
- **One request, one PAT.** A token is bound to the HTTP request that carried it: it authenticates
  only the GitLab calls made while serving that request, then is dropped. It is never cached, never
  stored in an MCP session (§5), and never used for any other request, including a later request
  from the same client or session. The shared outbound connection pool holds no credentials: the
  `Authorization` header is set on each GitLab call, and cookies GitLab sets are discarded.
  Redirects are refused, except on downloads (job logs, artifact files), where GitLab may hand
  off to object storage or a CDN through a signed URL. A hop to any other origin is made without
  the PAT, so a token is never forwarded to another host.
- The token is never logged, never written to disk, and never echoed back in tool output.
- Every GitLab API response's permission errors (`401`/`403`) pass through to the caller as MCP
  tool errors rather than being swallowed — the server enforces nothing beyond what the token
  itself already permits.
- **Token scope-aware tool visibility:** on each `tools/list`, the server resolves the scopes of
  that request's token (`api`, `read_api`, etc., via `GET /personal_access_tokens/self`, called with
  that same token) and hides actions the token cannot use (e.g. no write actions for a
  `read_api`-scoped token), the same behavior GitHub's server applies for classic PATs. If the
  lookup fails, nothing is hidden and GitLab's own `403`s apply.
- **No server-side token.** The `GITLAB_TOKEN` fallback in earlier drafts is removed: a shared server
  must never act as anyone but the caller. If `GITLAB_TOKEN` is set, the server logs a warning at
  startup and ignores it.

### 7.3 Future: OAuth 2.1 (Phase 2, not v1)

GitLab runs its own OIDC provider, so a spec-conformant OAuth 2.1 flow (PKCE, RFC 8707 resource
indicators, RFC 9728 metadata) is feasible later for interactive clients that want scoped,
revocable, non-PAT auth. Flagged here so PRD-01…08's tool designs don't assume PAT-only forever,
but it is not a v1 requirement.

### 7.4 Self-hosted GitLab support

- `GITLAB_BASE_URL` (default `https://gitlab.com/api/v4`) points the server at any GitLab CE/EE
  instance's REST API root.
- `GITLAB_CA_BUNDLE` (optional path) supports self-hosted instances with an internal/self-signed CA;
  TLS verification is **on by default** and disabling it requires an explicit, separately-named
  escape hatch (`GITLAB_SKIP_TLS_VERIFY=true`) that the server refuses to honor unless
  `GITLAB_BASE_URL` is not `gitlab.com` — never allow silently disabling verification against the
  public instance.

## 8. Configuration

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GITLAB_BASE_URL` | No | `https://gitlab.com/api/v4` | Target GitLab instance API root |
| `GITLAB_CA_BUNDLE` | No | system CAs | Custom CA for self-hosted instances |
| `GITLAB_SKIP_TLS_VERIFY` | No | `false` | Escape hatch for self-hosted only, refused against gitlab.com |
| `GITLAB_TIMEOUT_SECONDS` | No | `30` | Timeout for each GitLab call |
| `GITLAB_MAX_RETRIES` | No | `3` | Retry budget for `429`/`5xx` responses (§10) |
| `GITLAB_MAX_RESPONSE_BYTES` | No | 10 MiB | Largest GitLab response body the server will read (§10) |
| `GITLAB_MCP_TOOLSETS` | No | each toolset's default (§6) | Comma-separated toolset allow-list |
| `GITLAB_MCP_READ_ONLY` | No | `false` | Hide and refuse all mutating actions (§6) |
| `GITLAB_MCP_MAX_FILE_BYTES` | No | 1 MiB | Largest file content returned by file reads (PRD-02 §4) |
| `MCP_STATELESS_HTTP` | No | `true` | Stateless Streamable HTTP; `false` enables sessions (§5) |
| `MCP_SESSION_IDLE_TIMEOUT` | No | `1800` s | Evict idle sessions (stateful mode only) |
| `MCP_MAX_SESSIONS` | No | SDK default (10,000) | Cap concurrent sessions per instance (stateful mode only) |
| `MCP_BIND_HOST` / `MCP_BIND_PORT` | No | `127.0.0.1:8080` | Listener address |
| `MCP_ALLOWED_HOSTS` | When the bind isn't loopback | loopback names | `Host` header values accepted (§4.3) |
| `MCP_ALLOWED_ORIGINS` | No | loopback origins on a loopback bind, none otherwise | Browser `Origin` values accepted (§4.3) |
| `MCP_TLS_CERTFILE` / `MCP_TLS_KEYFILE` | No | — | Native TLS; set both or neither (§9) |
| `MCP_TLS_TERMINATED_UPSTREAM` | No | `false` | Declares that a proxy in front terminates TLS (§9) |
| `LOG_LEVEL` / `LOG_FORMAT` | No | `INFO` / `json` | Logging (§11) |

There is deliberately no `GITLAB_TOKEN` (§7.2).

## 9. Deployment & TLS

The repo and README both name this an **HTTPS** GitLab MCP server: the server must never be
reachable over plaintext HTTP in any deployment beyond local dev on `127.0.0.1`. TLS termination
(reverse proxy, e.g. behind nginx/Caddy/a cloud load balancer, or native TLS in the ASGI server) is
a hard requirement for any non-localhost bind address, enforced by refusing to start on a
non-loopback host without either TLS configured or an explicit `--insecure-dev` override. "TLS
configured" means either native TLS (`MCP_TLS_CERTFILE` + `MCP_TLS_KEYFILE`) or
`MCP_TLS_TERMINATED_UPSTREAM=true`, which declares that a reverse proxy or load balancer in front
terminates TLS. A non-loopback bind also requires `MCP_ALLOWED_HOSTS` (§4.3).

## 10. Error Handling, Retries & Pagination (shared conventions)

Every functional PRD (01–08) inherits these instead of defining its own:

- **Error classification:** GitLab `4xx` (bad input, permissions, not-found) map to MCP tool errors
  with the GitLab error message passed through. `429` is retried for any method, because GitLab
  rejected the call before doing anything. `5xx` is retried only for idempotent methods (`GET`,
  `HEAD`, `OPTIONS`, `PUT`, `DELETE`): a `POST` that failed with `5xx` may still have been applied
  (a commit created, a project forked), so repeating it could apply a write twice. It surfaces as a
  retryable tool error instead. Retries use exponential backoff with full jitter, bounded by
  `GITLAB_MAX_RETRIES`. Network failures get one retry: for any method when the connection was never
  established, otherwise only for idempotent methods.
- **Rate limiting:** honor GitLab's `Retry-After`/`RateLimit-Reset` response headers. A wait longer
  than the backoff ceiling (30 s) is not slept through; it is returned as a retryable error carrying
  `retry_after_seconds`. The per-caller outbound rate limit proposed here as a safety net is **not**
  built, because it needs state shared across requests and replicas — see §13 Q4.
- **Pagination:** GitLab REST list endpoints are page/per_page-based with `Link` headers and
  `X-Total`/`X-Page`/`X-Next-Page` response headers. Every list-style tool across every PRD accepts
  `page`/`per_page` (default `per_page=20`, capped at GitLab's max of 100) and returns pagination
  metadata to the caller rather than silently truncating or silently fetching all pages — large
  result sets (e.g. all commits on a long-lived branch, all jobs in a big pipeline) must be
  paged by the caller, never fully materialized server-side in one call.
- **Large payload discipline:** merge request diffs, job logs, and file contents can be large.
  Tools returning these must support a way to fetch a summary/list first and full content
  per-item second (e.g. "list changed files in this MR" then "get the diff for file X") rather than
  returning everything in one response — this is called out per-PRD where it applies (PRD-02, PRD-03,
  PRD-05). Two hard caps back this up: `GITLAB_MAX_RESPONSE_BYTES` for every GitLab response, and
  `GITLAB_MCP_MAX_FILE_BYTES` for file content.

## 11. Observability

- Structured JSON request logs: one event per tool call (tool, action, argument *names*, outcome,
  latency) and one per GitLab call (method, endpoint, status, attempt, latency, GitLab's own request
  ID). The caller's PAT, argument values, and GitLab response bodies are excluded from logs by
  default. Every line carries a request ID — the client's `X-Request-ID` when it's a safe token,
  otherwise a generated one.
- A health-check endpoint (`GET /healthz`, no credentials) separate from `/mcp` for deployment
  liveness/readiness probes.

## 12. Dependencies & Consumers

Every tool defined in PRD-01 through PRD-08 is a GitLab REST API call made through the connection
and auth mechanism defined here (§7), returns errors per §10, and is grouped into the toolset named
in that PRD (§6). None of those PRDs should redefine transport, session, or auth behavior.

## 13. Open Questions

1. **Protocol revision target (2025-11-25 vs. tracking 2026-07-28)** — implemented as recommended
   (§4.1). The SDK also serves 2026-07-28, so this is now low-stakes, but it still needs sign-off.
2. Is single-instance deployment (no horizontal scaling, no shared session store) acceptable for
   v1? Largely moot now: the stateless default (§5) scales horizontally with no sticky routing or
   shared store; only the optional stateful mode is single-instance.
3. Should the static-PAT fallback (`GITLAB_TOKEN`) be removed entirely? **Resolved: removed**, per
   the owner's requirement that every request use its caller's own PAT and no other (§7.2).
4. **Per-caller rate limiting.** §10's outbound safety-net limit isn't built: in a stateless,
   multi-replica deployment it needs a shared store keyed by a token hash. Proposal: leave abuse
   control (request rates, connection caps) to the reverse proxy or API gateway in front of the
   server. The `/mcp` gate only checks that a PAT is *present*; GitLab validates it on each call.

## Sources

- MCP Streamable HTTP transport (2025-03-26): https://modelcontextprotocol.io/specification/2025-03-26/basic/transports
- MCP Streamable HTTP transport (2025-11-25, target revision): https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
- MCP Authorization spec (2025-06-18): https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization
- MCP spec source/changelogs: https://github.com/modelcontextprotocol/modelcontextprotocol
- MCP TypeScript SDK: https://github.com/modelcontextprotocol/typescript-sdk
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- GitHub's remote MCP server (toolsets, auth, transport precedent): https://github.com/github/github-mcp-server, https://docs.github.com/en/copilot/how-tos/context/model-context-protocol/using-the-github-mcp-server
- Archived official GitLab reference server: https://github.com/modelcontextprotocol/servers-archived/tree/main/src/gitlab
- GitLab REST API resource index: https://docs.gitlab.com/api/api_resources.html
- GitLab native MCP server tools (product precedent for coarse "verb" tools): https://docs.gitlab.com/user/model_context_protocol/mcp_server_tools/
