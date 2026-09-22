# MCP-GitLab
HTTPS Gitlab MCP server that can connect to and work with non-enterprise Gitlab Servers using PATs

## Status

- **Transport:** MCP Streamable HTTP at `/mcp` (stateless by default), health check at `/healthz`.
- **Auth:** a shared server. Every request carries its caller's own GitLab PAT, used for that
  request only; the server holds no token of its own.
- **Tools:** `projects` (projects, branches, tags) and `repository` (tree, files and directories,
  commits), read and write. The remaining toolsets are specced in [`docs/prd/`](docs/prd/) but not
  built yet.

See [`CLAUDE.md`](CLAUDE.md) for the architecture, conventions, and how to add a toolset.

## Running

```
pip install .
mcp-gitlab        # serves http://127.0.0.1:8080/mcp
```

Configure it with environment variables or a `.env` file — see [`.env.example`](.env.example).
For a self-hosted instance set `GITLAB_BASE_URL=https://gitlab.example.com/api/v4`.

## Connecting a client

Send your PAT on every request. With Claude Code:

```
claude mcp add --transport http gitlab https://mcp.example.com/mcp \
  --header "Authorization: Bearer glpat-..."
```

GitLab's own `PRIVATE-TOKEN: <PAT>` header works too. A PAT with the `api` scope sees every action; a
`read_api` PAT sees read actions only. Optional headers:

- `X-MCP-Toolsets: projects` — use a subset of the toolsets the server allows.
- `X-MCP-Readonly: true` — hide and refuse every write action for this client.

Destructive actions (deleting a project or branch) also need `confirm: true` in the tool call.

## Deploying

Beyond `127.0.0.1` the server must be reached over HTTPS, and it refuses to start otherwise. Set:

- `MCP_BIND_HOST=0.0.0.0` and `MCP_ALLOWED_HOSTS=mcp.example.com` (the public hostname), plus
- `MCP_TLS_TERMINATED_UPSTREAM=true` behind a TLS-terminating proxy or load balancer, **or**
  `MCP_TLS_CERTFILE` and `MCP_TLS_KEYFILE` for native TLS.

The stateless default needs no sticky sessions, so replicas can sit behind any load balancer.

The [`Dockerfile`](Dockerfile) builds a non-root image that binds `0.0.0.0:8080` with a health
check on `/healthz`; pass `MCP_ALLOWED_HOSTS` and one of the TLS options to `docker run`. The image
build has not been tested yet.

## Development

```
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check . && mypy src && pytest
```
