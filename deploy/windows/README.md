# Windows service scripts (courtesy, not the intended deployment)

**This project's intended, supported deployment is Linux + Docker: the
[standalone image](../../README.md#standalone-image) with Caddy for TLS.** That is what CI builds,
tests, and publishes, and what [`CLAUDE.md`](../../CLAUDE.md) documents as the target platform.

The two scripts here are an example and a courtesy for Windows users who want to run `mcp-gitlab`
directly on Windows (no Docker/WSL) and have it come back after a logon, nothing more. They are
not tested by CI (there is no Windows runner for this project) and receive less scrutiny than the
rest of the codebase — read them before running them, as with any script from a repository.

## What they do

- **`install-service.ps1`** wraps the OS-independent `mcp-gitlab service start` (see
  [`src/mcp_gitlab/service.py`](../../src/mcp_gitlab/service.py)) in a Windows Scheduled Task, so
  it starts at your next logon, then starts it immediately.
- **`uninstall-service.ps1`** stops it and removes that scheduled task.

```powershell
cd deploy\windows
.\install-service.ps1
# ...
.\uninstall-service.ps1
```

Configure the server the same way as anywhere else: environment variables or a `.env` file next
to the `mcp-gitlab` executable (see [`.env.example`](../../.env.example) at the repository root).

## What they are not

This is **not** a real Windows Service. The task runs `mcp-gitlab` as an ordinary background
process for your logon session (or, with `-AtStartup`, under `SYSTEM`, which needs an elevated
prompt) — not under the Service Control Manager in Session 0. Logging off ends it, the same as
any other per-session background process. If you need it to run with nobody logged in, wrap
`mcp-gitlab serve` with a real service-hosting tool (for example NSSM, or `pywin32`'s
`win32serviceutil`) — deliberately not bundled here, since it would add a dependency this project
otherwise doesn't need.

For anything beyond "try it on my Windows machine," use the Linux/Docker deployment.
