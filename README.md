# MCP-GitLab
HTTPS Gitlab MCP server that can connect to and work with non-enterprise Gitlab Servers using PATs

## Status

- **Transport:** MCP Streamable HTTP at `/mcp` (stateless by default), health check at `/healthz`.
- **Auth:** a shared server. Every request carries its caller's own GitLab PAT, used for that
  request only; the server holds no token of its own.
- **Tools:** 26 tools in eight toolsets, read and write, one per PRD in [`docs/prd/`](docs/prd/):

  | Toolset | Tools |
  |---|---|
  | `projects` | `gitlab_projects`, `gitlab_branches`, `gitlab_tags`, `gitlab_badges` |
  | `repository` | `gitlab_repository_tree`, `gitlab_files`, `gitlab_commits` |
  | `merge_requests` | `gitlab_merge_requests`, `gitlab_mr_reviews` |
  | `issues` | `gitlab_issues`, `gitlab_issue_notes`, `gitlab_labels`, `gitlab_milestones` |
  | `pipelines` | `gitlab_pipelines`, `gitlab_jobs`, `gitlab_ci_variables`, `gitlab_pipeline_schedules`, `gitlab_runners` |
  | `releases` | `gitlab_releases`, `gitlab_release_links` |
  | `search` | `gitlab_search` |
  | `collaboration` | `gitlab_members`, `gitlab_users`, `gitlab_wikis`, `gitlab_webhooks`, `gitlab_snippets` |

  Each tool takes an `action` argument (for example `gitlab_branches` with `action: "create"`).
  Every toolset is on by default.

See [`CLAUDE.md`](CLAUDE.md) for the architecture, conventions, and how to add a toolset, and
[`LIMITATIONS.md`](LIMITATIONS.md) for known bugs, design decisions, and what isn't built.

## Running

```
pip install .
mcp-gitlab        # serves http://127.0.0.1:8080/mcp, in the foreground
```

Configure it with environment variables or a `.env` file — see [`.env.example`](.env.example).
For a self-hosted instance set `GITLAB_BASE_URL=https://gitlab.example.com/api/v4`.

`mcp-gitlab service start|stop|restart` instead runs it as a detached background process, tracked
by a pid file (`~/.mcp-gitlab/mcp-gitlab.pid` by default; override with `MCP_GITLAB_PID_FILE`).
It's plain Python (no `systemd`, no `schtasks`), so it works the same on Linux, macOS, and Windows.
The Docker deployment below remains the intended way to run this in production; `service` is for
running `mcp-gitlab` directly without Docker.

## Connecting a client

Send your PAT on every request. With Claude Code:

```
claude mcp add --transport http gitlab https://mcp.example.com/mcp \
  --header "Authorization: Bearer glpat-..."
```

GitLab's own `PRIVATE-TOKEN: <PAT>` header works too. A PAT with the `api` scope sees every action; a
`read_api` PAT sees read actions only, and a `read_user` PAT sees only `gitlab_users`. Optional
headers:

- `X-MCP-Toolsets: projects` — use a subset of the toolsets the server allows.
- `X-MCP-Readonly: true` — hide and refuse every write action for this client.

Destructive actions also need `confirm: true` in the tool call: deleting or transferring a
project, deleting a branch, all merged branches, an issue, a pipeline, or a runner, merging a
merge request, and changing or removing a project member.

## Deploying

Beyond `127.0.0.1` the server must be reached over HTTPS, and it refuses to start otherwise.

### Standalone image

One container holds everything: [Caddy](https://caddyserver.com) serves HTTPS on port 8443 and
passes each request, with its caller's PAT, to the MCP server, which listens only on the
container's loopback interface. CI publishes it to `ghcr.io/weatherills/mcp-gitlab`
(linux/amd64 and linux/arm64) from every push to `main`, tagged `latest` and `sha-<commit>`;
`v*` tags add version tags. It is pre-configured for this deployment, and both settings can be
overridden at run time:

- `MCP_PUBLIC_HOST=mantle.scipai.sandbox.sciencecloud.nasa.gov`, the name clients connect to;
- `GITLAB_BASE_URL=https://git.smce.nasa.gov/api/v4`.

[`deploy/`](deploy/) is a Docker Compose bundle for it, published on port 443:

```
cd deploy
mkdir certs && cp fullchain.pem certs/tls.crt && cp privkey.pem certs/tls.key
sudo chown 10001 certs/tls.key    # the container runs as uid 10001
docker compose up -d              # https://mantle.scipai.sandbox.sciencecloud.nasa.gov/mcp
```

Clients then connect as in [Connecting a client](#connecting-a-client), each with their own PAT.

**TLS.** Bring your own certificate, or let Caddy make one:

- **Your certificate:** `tls.crt` (the certificate, then any intermediates) and `tls.key` in
  `/certs` (`deploy/certs` in the bundle), readable by uid 10001; or name other files with
  `MCP_TLS_CERTFILE` and `MCP_TLS_KEYFILE`. It must cover `MCP_PUBLIC_HOST`. Caddy doesn't renew a
  certificate you provide: replace the files and restart the container before it expires.
- **No certificate:** Caddy creates a local CA on first start, then issues and renews the
  certificate itself. Clients must trust the CA's root certificate, which stays the same as long
  as the `/data` volume is kept:

  ```
  docker compose cp mcp-gitlab:/data/caddy/pki/authorities/local/root.crt mcp-gitlab-ca.crt
  ```

  Add it to the client machines' trust store, or for Claude Code set
  `NODE_EXTRA_CA_CERTS=/path/to/mcp-gitlab-ca.crt`.

Caddy answers any host name other than `MCP_PUBLIC_HOST` with `421`, and the server's
`MCP_ALLOWED_HOSTS` is derived from it. If a private CA issued GitLab's certificate, put that CA
bundle in `deploy/certs` and set `GITLAB_CA_BUNDLE=/certs/<file>` (it replaces the system CAs).
No Caddy log line includes request headers, so a PAT never reaches the logs.

**Getting the image.** GitHub makes a new package private: until an organization owner makes it
public (the package's settings, "Change visibility"; this can't be undone), pulling it needs
`docker login ghcr.io` with a PAT that has the `read:packages` scope. If the host can't reach
ghcr.io at all, carry the image over as a file:

```
docker pull --platform linux/amd64 ghcr.io/weatherills/mcp-gitlab:latest
docker save ghcr.io/weatherills/mcp-gitlab:latest | gzip > mcp-gitlab.tar.gz
# copy mcp-gitlab.tar.gz and deploy/ to the host, then, there:
docker load -i mcp-gitlab.tar.gz && docker compose up -d
```

Or build it: `docker compose build` in `deploy/`, or `docker build -t mcp-gitlab .`, which
defaults to `localhost` and gitlab.com unless given `--build-arg MCP_PUBLIC_HOST=...` and
`--build-arg GITLAB_BASE_URL=...`.

### Behind your own proxy or load balancer

Set:

- `MCP_BIND_HOST=0.0.0.0` and `MCP_ALLOWED_HOSTS=mcp.example.com` (the public hostname), plus
- `MCP_TLS_TERMINATED_UPSTREAM=true` behind a TLS-terminating proxy or load balancer, **or**
  `MCP_TLS_CERTFILE` and `MCP_TLS_KEYFILE` for native TLS.

The stateless default needs no sticky sessions, so replicas can sit behind any load balancer.
`docker build --target server .` builds an image of the server alone: non-root, binding
`0.0.0.0:8080`, with a health check on `/healthz`. Pass `MCP_ALLOWED_HOSTS` and one of the TLS
options to `docker run`.

CI builds both images, checks that they report healthy, and runs the Compose bundle in both TLS
modes before it publishes.

### Windows (courtesy scripts)

Linux + Docker (above) is the intended, supported deployment. [`deploy/windows/`](deploy/windows/)
has two PowerShell scripts that wrap `mcp-gitlab service start|stop` in a Windows Scheduled Task,
as an example and a courtesy for Windows users who want to run `mcp-gitlab` directly (no
Docker/WSL) and have it come back after a logon — not a substitute for the Docker deployment, and
not a real Windows Service (see that directory's README for what that distinction means in
practice).

## Development

```
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check . && mypy src && pytest
```
