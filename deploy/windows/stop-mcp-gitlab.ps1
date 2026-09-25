<#
.SYNOPSIS
Stops the mcp-gitlab-server scheduled task AND the real mcp-gitlab.exe
process it launched -- both, explicitly, not just one.

.DESCRIPTION
Stop-ScheduledTask alone is not enough: found live that it reliably
stops the wrapper (run-minimized.ps1) but leaves mcp-gitlab.exe itself
running, orphaned, still holding the port -- even with a Windows Job
Object explicitly set up to prevent exactly that (see run-minimized.ps1's
own comment for what was tried and ruled out). This script kills
mcp-gitlab.exe directly by the PID run-minimized.ps1 records to
mcp-gitlab.pid, rather than relying on Task Scheduler to reach it.

Use this instead of a bare Stop-ScheduledTask any time you need the
server to actually stop -- before a code update, a config change, or
just to free the port. install-service.ps1 and uninstall-service.ps1
already call this themselves before re-registering or removing the task.

.PARAMETER ProjectDir
Repository root. Defaults to two levels up from this script (this script
lives in deploy\windows\), which is where `.venv\Scripts\mcp-gitlab.exe`
and the pid file this script looks for both live by convention.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File deploy\windows\stop-mcp-gitlab.ps1
#>
param(
    [string]$ProjectDir = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

$TaskFullName = "MCP Servers\mcp-gitlab-server"
$PidFilePath = Join-Path $ProjectDir "data\mcp-gitlab.pid"

Stop-ScheduledTask -TaskName $TaskFullName -ErrorAction SilentlyContinue

if (Test-Path $PidFilePath) {
    $recordedPid = (Get-Content $PidFilePath -Raw -ErrorAction SilentlyContinue).Trim()
    if ($recordedPid -match '^\d+$') {
        $proc = Get-Process -Id ([int]$recordedPid) -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -eq "mcp-gitlab") {
            Stop-Process -Id $proc.Id -Force
            Write-Host "Stopped mcp-gitlab.exe (PID $($proc.Id))."
        }
    }
}

# Belt and suspenders: catch a mcp-gitlab.exe left behind by an older run
# whose PID file is stale or missing (e.g. upgrading from before this
# script existed). Filtered to the `serve` subcommand specifically, not a
# plain `Get-Process -Name mcp-gitlab`, since a plain name match would
# also catch whatever mcp-gitlab.exe invocation is CALLING this script
# (`mcp-gitlab service stop`/`restart` is itself a process named
# "mcp-gitlab", not just the server) -- that would kill its own caller
# mid-run with no warning.
Get-CimInstance Win32_Process -Filter "Name='mcp-gitlab.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match '\bserve\b' } |
    ForEach-Object {
        Write-Host "Stopping a leftover mcp-gitlab.exe (PID $($_.ProcessId))."
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Remove-Item $PidFilePath -ErrorAction SilentlyContinue

# Explicit success exit code -- without this, a stray non-terminating
# error along the way (e.g. Stop-ScheduledTask on a task that's already
# stopped, even with -ErrorAction SilentlyContinue) can leave the
# process's own exit code non-zero despite the script having done its job
# correctly, which trips a caller using -ErrorAction Stop or checking
# $LASTEXITCODE.
exit 0
