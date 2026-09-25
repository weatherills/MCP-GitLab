# MCP-GitLab — Fresh Windows PC Install (Local + Non-Local / HTTPS)

Repo: `https://github.com/weatherills/MCP-GitLab`
Transport: Streamable HTTP (`/mcp` + `/healthz`). Stateless by default.
Auth: **No server token.** Each client sends its own GitLab PAT per request via `Authorization: Bearer glpat-...` or GitLab's `PRIVATE-TOKEN: <PAT>`.
Tools: 26 tools, 8 toolsets (`projects`, `repository`, `merge_requests`, `issues`, `pipelines`, `releases`, `search`, `collaboration`).

Requires Python >=3.10 (Windows). Prefer PowerShell commands below (per project convention).

---

## 1. Prerequisites (Windows)

```powershell
# Option A: winget (recommended, no admin needed for user install)
winget install Python.Python.3.12

# Option B: chocolatey
choco install python

# Verify
python --version
```

Install Docker Desktop (only if doing non-local HTTPS deploy below).

---

## 2. Clone + Install (Local / Development)

```powershell
# Clone
cd C:\repos
# (Use HTTPS if you have no SSH key configured; GitLab PAT can also auth HTTPS)
git clone https://github.com/weatherills/MCP-GitLab.git
cd MCP-GitLab

# Virtual env + install
python -m venv .venv
.venv\Scripts\activate
pip install .

# Confirm installed
pip list | Select-String "mcp-gitlab"
```

---

## 3. Configure

```powershell
Copy-Item .env.example .env
# Edit .env (notepad, VS Code, etc.)
# Required for non-gitlab.com targets:
# GITLAB_BASE_URL=https://git.smce.nasa.gov/api/v4
```

Optional settings (see `.env.example`):
- `GITLAB_MCP_READ_ONLY=true`
- `GITLAB_MCP_TOOLSETS=projects,issues`
- `LOG_LEVEL=INFO`

---

## 4. Run — Local Only (HTTP on loopback)

```powershell
# From repo root, venv active
mcp-gitlab
# Endpoint: http://127.0.0.1:8080/mcp
# Health:   http://127.0.0.1:8080/healthz
```

**Verify (run this check):**
```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8080/healthz" -UseBasicParsing -ErrorAction SilentlyContinue
# Expected: StatusCode 200; body shows healthy
```

**Important for non-local:** The server **refuses to start** over non-loopback unless TLS is configured (see §7). For testing from another PC on the same LAN, use the HTTPS deploy in §7.

---

## 5. Connect Clients

Every client sends its own PAT. The server never stores one. Use a GitLab PAT with at least `read_api`; use `api` scope for write actions (`destructive` actions additionally require `confirm: true` in the tool call).

### 5.1 PageAssist (Browser Extension — Chrome / Firefox)

1. Install PageAssist (https://pageassist.xyz/ or store).
2. Open extension → **Settings → MCP Settings**.
3. Add new server:
   - **URL:** `http://127.0.0.1:8080/mcp`
   - **Auth type:** Bearer
   - **Token:** `glpat-xxxxxxxxxxxxxxxxxxxx` (your GitLab PAT)
4. Optional filters (apply per-request if supported):
   - `X-MCP-Readonly: true`
   - `X-MCP-Toolsets: projects,issues`
5. For Firefox origin note: find extension ID at `about:debugging#/runtime/this-firefox`.

**Verification:** Ask extension to call `gitlab_projects(action="list")`.

---

### 5.2 Claude Code (CLI / Anthropic)

```powershell
claude mcp add --transport http gitlab http://127.0.0.1:8080/mcp `
  --header "Authorization: Bearer glpat-xxxxxxxxxxxxxxxxxxxx"
claude mcp list
claude mcp get gitlab
```

---

### 5.3 Cursor (AI Editor)

Add to `%APPDATA%\Cursor\mcp.json` (or project `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "gitlab": {
      "url": "http://127.0.0.1:8080/mcp",
      "headers": {
        "Authorization": "Bearer glpat-xxxxxxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

Restart Cursor / reload window.

---

### 5.4 VS Code (Copilot / Agent / MCP)

Add to User / Workspace settings (`.vscode/settings.json` or global):

```json
{
  "mcpServers": {
    "gitlab": {
      "command": "echo",
      "env": {},
      "args": ["not-used"],
      "url": "http://127.0.0.1:8080/mcp",
      "headers": {
        "Authorization": "Bearer glpat-xxxxxxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

Note: VS Code native Streamable HTTP support requires 1.99+ / Copilot agent mode. If needed, proxy through LiteLLM (see `LITELLM.md`).

For Copilot BYOK / agent host, verify:
- `chat.agentHost.enabled`: true
- `chat.agentHost.byokModels.enabled`: true

---

## 6. Testing / Verification Commands

```powershell
# Installed correctly?
pip show mcp-gitlab

# Health endpoint?
Invoke-WebRequest -Uri "http://127.0.0.1:8080/healthz" -UseBasicParsing

# Tool list (direct call with valid PAT)
Invoke-RestMethod -Uri "http://127.0.0.1:8080/mcp" `
  -Method POST -ContentType "application/json" `
  -Headers @{ Authorization = "Bearer glpat-..." } `
  -Body '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

---

## 7. Non-Local / HTTPS Install (Windows — Public or LAN Access)

The server **must use HTTPS** when reachable beyond `127.0.0.1`. The repo provides a Caddy-based standalone image (`deploy/`).

### 7.1 Option A — Docker Compose (Recommended for Windows Server / Azure VM / LAN host)

```powershell
cd deploy
mkdir certs

# If you have real certs (Let's Encrypt / Azure Key Vault / manual PEM):
# cp C:\certs\fullchain.pem certs\tls.crt
# cp C:\certs\privkey.pem certs\tls.key
# (Docker Desktop on Windows handles permissions differently; for WSL2/Linux host use chown)

# If NO cert: Caddy creates local CA + self-signed (see §7.3 for client trust)

# Start
docker compose up -d

# Verify (from host)
Invoke-WebRequest -Uri "https://localhost/mcp" -SkipCertificateCheck -UseBasicParsing
```

**Key settings (env / compose):**
- `MCP_PUBLIC_HOST=mcp.example.com` (must match TLS cert SAN; Caddy answers 421 otherwise)
- `GITLAB_BASE_URL=https://git.smce.nasa.gov/api/v4` (or your GitLab)
- `MCP_BIND_HOST=0.0.0.0` (Caddy binds; server stays loopback inside container)

### 7.2 Option B — Standalone Image Directly

```powershell
docker pull ghcr.io/weatherills/mcp-gitlab:latest
# Or build locally
docker build -t mcp-gitlab .
```

### 7.3 Client Trust for Non-Local / Self-Signed Cert (Caddy Local CA)

```powershell
# Extract CA root (WSL2 / Linux host command; adjust if pure Windows container)
docker compose cp mcp-gitlab:/data/caddy/pki/authorities/local/root.crt mcp-gitlab-ca.crt

# For Node-based clients (Claude, Cursor, VS Code):
$env:NODE_EXTRA_CA_CERTS = "C:\certs\mcp-gitlab-ca.crt"
# Add to environment permanently if needed

# For PageAssist: trust cert in browser store or add exception.
```

---

## 8. Security / PAT Notes (Per Request)

- **Scope:** `read_api` = read-only; `api` = full; `read_user` = users only.
- **Headers:** `Authorization: Bearer glpat-...` (preferred) or `PRIVATE-TOKEN: glpat-...`.
- **Destructive:** Deleting projects/branches/issues/pipelines, merging MRs, removing members — requires `confirm: true` in tool call (dispatcher enforces).
- **Read-only override:** `X-MCP-Readonly: true`.
- **No server storage:** The server never caches, logs (redacted), or stores the PAT. Each tool call creates a new `GitLabSession` from request headers.

---

## 9. Troubleshooting (Quick)

| Problem | Check |
|---|---|
| Server won't start (non-local) | Must have TLS cert or Caddy local CA; must set `MCP_PUBLIC_HOST` matching cert |
| 401 from client | PAT missing / wrong header; use `Authorization: Bearer ...` |
| 403 from GitLab | PAT scope too narrow; use `api` for writes |
| Client can't connect | Loopback = `http://127.0.0.1:8080`; Non-local = `https://host/mcp` + cert trust |
| PageAssist origin errors | Extension sends `Origin`; server uses request-level auth (no allowed_origins needed for this shared-PAT design unless you add a token gate) |

---

## 10. References

- Repo: https://github.com/weatherills/MCP-GitLab
- README (transport, clients, deploy): `README.md`
- Architecture / toolset specs: `CLAUDE.md`, `docs/prd/PRD-00-architecture.md`
- Compose / Caddy deploy: `deploy/`
- .env template: `.env.example`
- Multi-user LLM + MCP gateway via LiteLLM: `LITELLM.md`
