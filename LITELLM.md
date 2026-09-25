# Connecting MCP-GitLab to LiteLLM

How to put [LiteLLM Proxy](https://docs.litellm.ai/) in front of this server so that any number of
users, on any MCP-capable harness, can reach both a configured LLM and this server's GitLab tools
through one deployment — without breaking this project's own rule that every GitLab action carries
its caller's own PAT, never a shared one (`CLAUDE.md`'s owner requirement #1).

> **Before you rely on this document:** LiteLLM's MCP-gateway feature (the part of this doc beyond
> "Topology A") is newer than its core LLM-proxy feature and moves fast. The field names and
> examples below were checked against LiteLLM's published docs as of 2026-09-25, cited under
> [References](#references) — confirm them against the docs for the LiteLLM version you actually
> run before depending on this in production, especially anything under
> [Topology B](#topology-b-one-endpoint-for-both-llm-and-mcp-tools).

## The two things LiteLLM can do here

LiteLLM Proxy is two mostly-independent features bolted together:

1. **An OpenAI-compatible LLM gateway.** Point any harness's "OpenAI base URL" at LiteLLM instead
   of a provider directly, and LiteLLM routes to whichever of 100+ providers/models you've
   configured, with per-user virtual keys, budgets, and rate limits. This part is mature and
   stable, and has nothing to do with MCP.
2. **An MCP gateway** (newer). LiteLLM can itself present an MCP endpoint that aggregates one or
   more *backend* MCP servers — this GitLab server among them — behind one URL, with its own
   per-key/per-team access control on top of whatever the backend server enforces.

You don't have to use #2 to get multi-user LLM access, and #2 is genuinely optional. Pick based on
what your harnesses need:

| | Topology A: decoupled | Topology B: unified gateway |
|---|---|---|
| LLM calls | via LiteLLM | via LiteLLM |
| GitLab tool calls | direct to `mcp-gitlab`, harness's own PAT header | via LiteLLM's `/{alias}/mcp`, PAT forwarded through LiteLLM |
| Setup complexity | Lowest — two independent, already-multi-user systems | Higher — one more moving part, newer LiteLLM feature |
| Use when | Your harness can add an MCP server with a custom header (most can — this is what `README.md` and `INSTALL.md` already document) | Your harness wants one URL for everything, or can't be configured with more than one bearer token (LiteLLM's stored-credential mode, [B2](#b2-stored-per-user-credential-one-token-harnesses)) |

Both topologies need `mcp-gitlab` itself deployed and reachable exactly as `README.md` and
`INSTALL.md` already describe (HTTPS off-loopback, `MCP_ALLOWED_HOSTS`, etc.) — LiteLLM changes
nothing about how this server is run; it's just one more authenticated caller of it.

## Topology A: decoupled (recommended default)

Use LiteLLM only as the LLM layer. The harness talks to `mcp-gitlab` directly for tools, exactly as
`README.md`'s "Connecting a client" section and `INSTALL.md` §5 already show. Nothing about that
changes here — this section only covers the LiteLLM side.

### 1. Minimal LiteLLM config

```yaml
# litellm_config.yaml
model_list:
  - model_name: my-model                    # what harnesses will ask for
    litellm_params:
      model: anthropic/claude-sonnet-5       # swap for whatever provider/model you're routing to
      api_key: os.environ/ANTHROPIC_API_KEY

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY  # admin key: mints virtual keys, never handed to users
```

```
export ANTHROPIC_API_KEY=...
export LITELLM_MASTER_KEY=sk-...            # generate a real random value
litellm --config litellm_config.yaml --port 4000
```

### 2. One virtual key per user

Each user gets their own LiteLLM **virtual key** — this is LiteLLM's multi-user primitive: a key
carries its own budget, rate limits, and model access list, and every call's spend is attributed to
the key (and its user/team) that made it:

```
curl -s http://localhost:4000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"user_id": "alice", "models": ["my-model"], "max_budget": 20, "budget_duration": "30d"}'
```

Group related users under a **team** (`/team/new`, then generate keys with `"team_id"`) if you want
a shared budget or shared model-access list rather than per-user ones — see LiteLLM's
[Multi-Tenant Architecture](https://docs.litellm.ai/docs/proxy/multi_tenant_architecture) doc for
the team/user/key hierarchy. None of this involves GitLab; it's purely about who may call which
model, and how much they may spend doing it.

### 3. Point the harness at both

- **LLM:** OpenAI-compatible base URL `http://<litellm-host>:4000/v1`, API key = that user's virtual
  key (`sk-...` from step 2), model name `my-model`.
- **GitLab tools:** add `mcp-gitlab` as an MCP server exactly as already documented (`README.md`
  "Connecting a client", `INSTALL.md` §5), with that same user's **own GitLab PAT** as
  `Authorization: Bearer <PAT>`.

These are two separate credentials for two separate systems, on purpose: LiteLLM's virtual key never
touches GitLab, and the GitLab PAT never touches LiteLLM. A harness that can hold two independent
bearer tokens (basically all of them — see `INSTALL.md` §5's Claude Code, Cursor, and VS Code
examples) needs nothing more than this.

## Topology B: one endpoint for both LLM and MCP tools

Use this when you want a single URL a harness talks to for everything, or when a harness genuinely
can't be configured with the GitLab PAT as a second header (Topology A's requirement) — LiteLLM's
MCP gateway can then hold that PAT on the user's behalf instead (§B2).

### Register `mcp-gitlab` as a backend MCP server

```yaml
# litellm_config.yaml — adds to the model_list from Topology A
mcp_servers:
  gitlab:
    url: "https://mcp.example.com/mcp"   # your mcp-gitlab deployment, per README's Deploying section
    transport: "http"                     # Streamable HTTP — what mcp-gitlab speaks natively
    auth_type: "none"                     # see the warning below — do not use a static credential here
```

> **Do not set `auth_type: token` / `auth_value` here.** That pattern gives LiteLLM one fixed,
> shared upstream credential to use for *every* caller — which for this server means one GitLab
> identity for every user's every action: no per-user audit trail in GitLab, and a direct violation
> of this repo's own non-negotiable rule that every request carries its own caller's PAT
> (`CLAUDE.md`). Use `auth_type: none` and forward each user's real PAT per request (below) instead.

### B1. Per-request header passthrough (most harnesses)

LiteLLM forwards a `x-mcp-{server_alias}-{header_name}` header to that specific backend server,
stripping the prefix. For the `gitlab` alias above, a client sends its GitLab PAT as:

```
x-mcp-gitlab-authorization: Bearer glpat-xxxxxxxxxxxxxxxxxxxx
```

and LiteLLM relays it upstream as plain `Authorization: Bearer glpat-...` — exactly the header
`mcp-gitlab` already expects, no server-side rewriting needed (LiteLLM's `upstream_token_header`
config option exists for backends that need a differently-named header; `mcp-gitlab` doesn't).

A harness adds the gateway as one MCP server, at `<litellm-base-url>/gitlab/mcp`, with **two**
headers — the LiteLLM virtual key (gateway auth) and the user's own GitLab PAT (forwarded through):

```
claude mcp add --transport http gitlab-via-litellm http://localhost:4000/gitlab/mcp \
  --header "x-litellm-api-key: Bearer sk-<alice's virtual key>" \
  --header "x-mcp-gitlab-authorization: Bearer glpat-<alice's PAT>"
```

(`x-litellm-api-key` is LiteLLM's own convention for its key on MCP traffic, so that plain
`Authorization` stays free for an upstream OAuth flow when one's in play — it isn't needed here
since GitLab PATs aren't OAuth, but LiteLLM still prefers it for its own auth on `/mcp` routes.)
Every user configures the same URL with their *own* two values. This is functionally identical to
Topology A's two-headers-on-one-harness model — it's just that both now point at LiteLLM instead of
one pointing at `mcp-gitlab` directly.

### B2. Stored per-user credential (one-token harnesses)

For a harness that can only carry a single token per MCP server (nowhere to put a second header),
LiteLLM can instead hold each user's GitLab PAT itself, resolved by the caller's `user_id`/virtual
key rather than resent on every call — LiteLLM's docs call this
[per-user and per-key upstream credentials](https://docs.litellm.ai/docs/mcp_per_user_auth). Each
user registers their PAT with LiteLLM once (via its Admin UI or API, tied to their `user_id`); after
that, a harness needs only `x-litellm-api-key: Bearer <their virtual key>` and LiteLLM attaches the
right PAT for that user automatically.

**This is a real tradeoff, not a free upgrade:** the PAT now lives at rest in LiteLLM's own
credential store, a second place it can be read, exported, or leaked from — `mcp-gitlab` itself
still never stores it, but the overall system now has a place that does. Use B1 unless a harness's
limitations genuinely require B2, and secure LiteLLM's database/secrets store accordingly if you do
(LiteLLM's own docs cover encrypting stored credentials).

### Debugging a gateway connection

`x-litellm-mcp-debug: true` on a request returns diagnostic response headers showing what LiteLLM
resolved for upstream auth — useful for confirming the PAT you think you sent is the one that
actually reached `mcp-gitlab`, without needing to check `mcp-gitlab`'s own logs (which, per
`CLAUDE.md`, never contain the PAT itself either way).

### Layering permissions (optional, defense in depth)

LiteLLM's [MCP permission management](https://docs.litellm.ai/docs/mcp_control) can restrict which
of `mcp-gitlab`'s tools a given key or team may call at all (`allowed_tools`, `access_groups`,
`object_permission.mcp_tool_permissions`) — evaluated *before* the call ever reaches `mcp-gitlab`.
This stacks with, and doesn't replace, `mcp-gitlab`'s own independent controls: `X-MCP-Readonly` /
`GITLAB_MCP_READ_ONLY` (refuses every write action) and `X-MCP-Toolsets` / `GITLAB_MCP_TOOLSETS`
(narrows which toolsets are visible at all) — see `README.md`. Restricting at both layers means a
misconfiguration in one doesn't fully undo the other; neither is a substitute for scoping each
user's actual GitLab PAT to the access they should have, which is still the only control that's
enforced by GitLab itself rather than by either proxy.

## The two identities, and the rule that doesn't change

| | Governs | Held by | Multi-user via |
|---|---|---|---|
| LiteLLM virtual key | LLM model access, spend, rate limits | LiteLLM (its own DB) | `/key/generate`, teams, budgets |
| GitLab PAT | What the caller can do in GitLab, and whose name it's done under | The caller (Topology A, B1) or LiteLLM's credential store (B2 only) | Each user has their own PAT — never shared |

Whatever topology you pick, the GitLab PAT stays one-per-user. Putting a single shared PAT anywhere
in this chain — LiteLLM's `auth_value`, a `.env` file, a "service account" everyone's harness
points at — defeats the reason `mcp-gitlab` is built the way it is (`CLAUDE.md` owner requirement
#1): every GitLab action would then be attributed to one identity for every person using it, with no
way to tell them apart in GitLab's own audit log, and no way to give one user narrower GitLab
permissions than another.

## Testing your setup

```
# 1. LLM call through LiteLLM
curl -s http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-<a virtual key>" -H "Content-Type: application/json" \
  -d '{"model": "my-model", "messages": [{"role": "user", "content": "ping"}]}'

# 2a. Topology A — tools/list straight to mcp-gitlab
curl -s https://mcp.example.com/mcp -H "Authorization: Bearer glpat-..." \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# 2b. Topology B — the same, through LiteLLM's gateway
curl -s http://localhost:4000/gitlab/mcp \
  -H "x-litellm-api-key: Bearer sk-<a virtual key>" \
  -H "x-mcp-gitlab-authorization: Bearer glpat-..." \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

A `tools/list` result you can read means auth reached `mcp-gitlab` correctly; a shorter list than
expected (or none) usually means the PAT's scope, not the LiteLLM wiring — check the token's scopes
first (`mcp-gitlab` hides write actions from a `read_api`-only token, for instance).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `401` from LiteLLM itself | Missing/invalid `x-litellm-api-key` (or `Authorization`, outside MCP routes) |
| `401` from `mcp-gitlab` (via LiteLLM or direct) | GitLab PAT missing, wrong header name, or not forwarded — check with `x-litellm-mcp-debug: true` in Topology B |
| Tool list shorter than expected | The GitLab PAT's scope, not LiteLLM — `mcp-gitlab` hides actions a token's scope can't use |
| `421` connecting to `mcp-gitlab` | Its `MCP_ALLOWED_HOSTS`/Caddy `MCP_PUBLIC_HOST` doesn't match the Host LiteLLM is sending — this is `mcp-gitlab`'s own deployment config, unrelated to LiteLLM (see `README.md` Deploying) |
| Works in Topology A's direct curl but not through LiteLLM | The `x-mcp-{alias}-` prefix or alias name doesn't match the `mcp_servers` key in `litellm_config.yaml` |

## References

Verified via search against LiteLLM's published docs on 2026-09-25 (direct fetch of
`docs.litellm.ai` wasn't reachable from the environment that wrote this — cross-check these before
relying on them for anything beyond what this document already spells out):

- [MCP Overview](https://docs.litellm.ai/docs/mcp) · [MCP Configuration Reference](https://docs.litellm.ai/docs/mcp_config_reference) · [MCP Non-OAuth Authentication](https://docs.litellm.ai/docs/mcp_authentication)
- [MCP Per-User and Per-Key Upstream Credentials](https://docs.litellm.ai/docs/mcp_per_user_auth) · [Using your MCP](https://docs.litellm.ai/docs/mcp_usage) · [MCP Troubleshooting Guide](https://docs.litellm.ai/docs/mcp_troubleshoot)
- [MCP Permission Management](https://docs.litellm.ai/docs/mcp_control) · [Grant MCP Server Access to Keys and Teams](https://docs.litellm.ai/docs/mcp_grant_access)
- [Use Claude Code with MCPs](https://docs.litellm.ai/docs/tutorials/claude_mcp) (the `<base>/<alias>/mcp` + `x-litellm-api-key` pattern generalized above)
- [Multi-Tenant Architecture with LiteLLM](https://docs.litellm.ai/docs/proxy/multi_tenant_architecture) · [Virtual Keys](https://docs.litellm.ai/docs/proxy/virtual_keys) · [Budgets, Rate Limits](https://docs.litellm.ai/docs/proxy/users)

In this repo: `README.md` ("Connecting a client", "Deploying"), `INSTALL.md` §5 (the harness
examples this doc's Topology A reuses unchanged), `CLAUDE.md` (owner requirement #1), `.env.example`.
