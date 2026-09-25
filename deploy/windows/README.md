# Windows autostart scripts (courtesy, not the intended deployment)

**This project's intended, supported deployment is Linux + Docker: the
[standalone image](../../README.md#standalone-image) with Caddy for TLS.** That is what CI builds,
tests, and publishes, and what [`CLAUDE.md`](../../CLAUDE.md) documents as the target platform.

The scripts here are an example and a courtesy for Windows users who want to run `mcp-gitlab`
directly on Windows (no Docker/WSL) and have it come back after a logon, nothing more. They are
not tested by CI (there is no Windows runner for this project) and receive less scrutiny than the
rest of the codebase — read them before running them, as with any script from a repository.

## What they do

- **`install-service.ps1`** registers `mcp-gitlab serve` as a Windows Scheduled Task under
  `MCP Servers\mcp-gitlab-server`, sets it to restart automatically if it exits unexpectedly, and
  starts it immediately. No elevated (Administrator) prompt is needed for the default case
  (installing for yourself).
- **`uninstall-service.ps1`** stops it and removes that scheduled task and its auto-start entry.
- **`run-minimized.ps1`**, **`stop-mcp-gitlab.ps1`**, and **`start-mcp-gitlab-at-logon.vbs`** are
  helpers the two scripts above use internally — you shouldn't normally need to run these
  yourself. `stop-mcp-gitlab.ps1` is also useful directly any time you want to stop the server
  without removing the task (before an update, for example).

```powershell
cd deploy\windows
.\install-service.ps1
# ...
.\uninstall-service.ps1
```

Both `install-service.ps1` and `uninstall-service.ps1` take `-Help` to print usage and exit
without taking any action.

Configure the server the same way as anywhere else: environment variables or a `.env` file next
to the `mcp-gitlab` executable (see [`.env.example`](../../.env.example) at the repository root).

### Why a Scheduled Task with no logon trigger, run through two wrapper scripts

None of this is decorative — each piece works around a specific failure found live while building
it, on a machine that turned out to block the more obvious approach:

- **`schtasks.exe` + a raw XML task definition, not the `ScheduledTasks` PowerShell module's
  `Register-ScheduledTask`.** On a managed machine, `Register-ScheduledTask` (which talks to the
  newer, WMI-based task provider) failed outright with a flat "Access is denied." `schtasks.exe` —
  which talks to the same classic Task Scheduler API the Task Scheduler GUI itself uses — worked
  immediately, same account, same session, no elevation. This also turned out to be the actual
  cause of two separate symptoms from earlier versions of these scripts: a task that opened a
  window and closed it immediately with no output when started on demand, and
  `Register-ScheduledTask`'s own "No mapping between account names and security IDs was done."
  Both were WMI-path failures, not problems with the task definition itself.
- **No `LogonTrigger` on the task; a Startup-folder script (`start-mcp-gitlab-at-logon.vbs`)
  triggers it instead.** Bisecting the same "Access is denied" turned up something more specific:
  on that same machine, registering a task with a full `RestartOnFailure` settings block, an
  explicit `Principal`/`UserId`, even *starting* the task on demand — all of it worked, except
  adding a `LogonTrigger` specifically, which alone reproduced the Access Denied. Almost certainly
  a security policy blocking auto-start-at-logon registration in particular, since that's a
  classic persistence technique — not a general Task Scheduler restriction. The default task is
  registered with no triggers at all; `install-service.ps1` copies `start-mcp-gitlab-at-logon.vbs`
  into your Startup folder, and that script just runs `schtasks /run` on the (trigger-less) task
  once at logon, with no visible window of its own. Task Scheduler's own `RestartOnFailure` keeps
  the task running/restarting from then on regardless of what started that particular run — it
  isn't tied to the trigger.
- **`run-minimized.ps1` wraps the actual launch, routed through `conhost.exe --headless`.** Task
  Scheduler's Action has no window-style setting of its own, so launching `mcp-gitlab.exe` directly
  always shows its console window. `run-minimized.ps1` uses `Start-Process -WindowStyle Minimized`
  instead, which needs `ShellExecute` internally and so needs its own script to call it from,
  rather than being an option on the task's Action directly. It's also why the wrapper has to wait
  for the target and forward its real exit code: Task Scheduler's restart-on-failure is keyed on
  the exit code of the process it's directly tracking, so a wrapper that launched and returned
  immediately would report "completed successfully" and Task Scheduler would stop watching it,
  even while the real process kept running (or later crashed) underneath. Routed through
  `conhost.exe --headless` specifically because, on a machine with Windows Terminal set as the
  default terminal application, a bare `powershell.exe` launch — even hidden — still opened a
  visible Windows Terminal tab; `conhost.exe --headless` sidesteps that "default terminal"
  resolution entirely.
- **`stop-mcp-gitlab.ps1` kills `mcp-gitlab.exe` by PID, not just `Stop-ScheduledTask`.** Stopping
  the task alone was found to reliably leave the real server process running, orphaned, still
  holding the port — even with a Windows Job Object explicitly set up to prevent exactly that. This
  script kills the process directly by the PID `run-minimized.ps1` records to `data\mcp-gitlab.pid`
  instead, which is deterministic regardless of what launched it. Both `install-service.ps1` (before
  re-registering) and `uninstall-service.ps1` call this rather than stopping the task directly.

None of the above has been verified by actually running these scripts on a real Windows machine —
there is no Windows box in the environment that wrote them. Each finding above came from live
runs on machines encountered while building this; if your machine behaves differently, the
comments at the top of each script are the place to start.

### Installing on behalf of another account, or at system startup

`-Username` registers the task to run as a different account than whoever runs the script — for
when an administrator sets this up on behalf of a user or service account, rather than for
themselves. No password is needed or stored: the task still has no trigger of its own, same as the
default case. This **does** need an elevated (Administrator) prompt — Windows requires that to
register (or remove) a task under an account other than the one running the script, regardless of
which API does it. Because `[Environment]::GetFolderPath("Startup")` always resolves to the
*calling* account's own Startup folder, not `-Username`'s, the script can't place
`start-mcp-gitlab-at-logon.vbs` there for you; it prints the file's path and tells you to copy it
into that account's Startup folder by hand (sign in as them and use `shell:startup`, or reach their
profile over a share).

```powershell
# Run elevated: registers the task for svc_mcpgitlab, not whoever runs this command.
.\install-service.ps1 -Username "CONTOSO\svc_mcpgitlab"
# ... later, from the same or another elevated prompt:
.\uninstall-service.ps1 -Username "CONTOSO\svc_mcpgitlab"
```

`-AtStartup` triggers the task at system boot instead of at a logon, running as `SYSTEM` — for a
machine with no interactive user. This also needs an elevated prompt, and is the one case that
still uses a real trigger (a `BootTrigger`): `SYSTEM` has no logon of its own for a Startup-folder
item to piggyback on. Mutually exclusive with `-Username`.

## What they are not

This is **not** a real Windows Service. The task runs `mcp-gitlab` as an ordinary background
process for your logon session (or, with `-AtStartup`, under `SYSTEM`, which needs an elevated
prompt) — not under the Service Control Manager in Session 0. Logging off ends it, the same as
any other per-session background process. If you need it to run with nobody logged in, wrap
`mcp-gitlab serve` with a real service-hosting tool (for example NSSM, or `pywin32`'s
`win32serviceutil`) — deliberately not bundled here, since it would add a dependency this project
otherwise doesn't need.

For anything beyond "try it on my Windows machine," use the Linux/Docker deployment.
