<#
.SYNOPSIS
Launches a target executable minimized, records its PID, waits for it to
exit, and forwards its exit code. Used by the mcp-gitlab-server scheduled
task so its console window doesn't pop up at logon.

.DESCRIPTION
Task Scheduler's own Action has no window-style setting -- launching an
.exe directly always shows its console window (or, with <Hidden>true</Hidden>
in the task's Settings, suppresses it entirely, which is not the same
thing as minimized and can't be restored). This script is the standard
workaround: Task Scheduler runs *this* script instead of mcp-gitlab.exe
directly, and this script uses Start-Process -WindowStyle Minimized to
launch the real target with its window already minimized.

Deliberately Start-Process (the cmdlet), not System.Diagnostics.Process
with UseShellExecute=false directly, even though that was tried: found
live that with UseShellExecute=false, the target inherits this wrapper's
own (hidden) console instead of getting a new one of its own --
MainWindowHandle came back 0, and the target's stdout showed up directly
in the *caller's* console instead, confirming it never got a separate
window at all, so there was nothing for WindowStyle to minimize.
-WindowStyle on the Start-Process cmdlet specifically forces
UseShellExecute=true internally (documented -- it's why -WindowStyle and
the redirection parameters are mutually exclusive on this cmdlet), and a
ShellExecute-launched process reliably gets its own new, genuinely
minimized window instead of inheriting the caller's console. Confirmed
live via a real Win32 GetWindowPlacement check (showCmd == 2).

-Wait (via -Wait on Start-Process) and forwarding the real exit code
matter for a separate reason: Task Scheduler's restart-on-failure only
triggers based on the exit code of the process it's directly tracking.
Without waiting and forwarding the real exit code, this wrapper would
exit immediately after launching the target (success, code 0), Task
Scheduler would consider that one run "completed" and stop watching it,
and a later crash would never trigger a restart.

$PidFilePath records the target's real PID for stop-mcp-gitlab.ps1 to
use, rather than relying on Task Scheduler to reach it: also found live,
a Windows Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, with the
target explicitly assigned via AssignProcessToJobObject (which reported
success every time), did NOT reliably kill the target when this wrapper
was stopped by Stop-ScheduledTask -- across several different launch
mechanisms, all verified via real Get-Process checks before/after.
Rather than keep chasing undocumented job-object behavior in this
specific environment, stop-mcp-gitlab.ps1 kills the target directly by
PID instead -- fully deterministic, and it doesn't matter which launch
mechanism was used.
#>
param(
    [Parameter(Mandatory)][string]$Target,
    [Parameter(Mandatory)][string]$Arguments,
    [Parameter(Mandatory)][string]$WorkingDirectory,
    [Parameter(Mandatory)][string]$PidFilePath
)

# Found live: the -WindowStyle Hidden passed to *this* script's own
# powershell.exe invocation (in install-service.ps1's task Action) does
# not reliably suppress this wrapper's own console window on every
# machine -- it stayed visible, sometimes as a normal window and at least
# once observed as minimized-but-not-hidden, for as long as the wrapper
# ran (the server's entire lifetime). Explicitly hiding it here via
# GetConsoleWindow + ShowWindow(SW_HIDE) does not depend on -WindowStyle
# having taken effect at all -- confirmed this actually hides it -- but a
# single one-shot call right at startup was itself found to still
# sometimes leave it visible, almost certainly a race: either the console
# window isn't fully created yet the instant this script starts
# (GetConsoleWindow returning 0 or a not-yet-final handle), or something
# later in the -WindowStyle Hidden launch sequence re-shows it after this
# call already ran. Polling for the handle and re-asserting the hide a
# few times over the first second closes that race without depending on
# understanding its exact cause.
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class ConsoleWindow {
    [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@
function Hide-ThisConsole {
    $hwnd = [ConsoleWindow]::GetConsoleWindow()
    if ($hwnd -ne [IntPtr]::Zero) {
        [ConsoleWindow]::ShowWindow($hwnd, 0) | Out-Null  # 0 = SW_HIDE
        return $true
    }
    return $false
}

# Deliberately BEFORE Start-Process, not after -- tried hiding after
# launching the target (on the theory that the retry loop could then run
# concurrently with the target starting up, costing no startup latency)
# and found live it regresses completely: the wrapper's window then
# stayed visible for the entire run, every time, not just intermittently.
# Whatever Start-Process -WindowStyle Minimized does internally (it forces
# ShellExecute, per this script's own earlier notes) evidently interferes
# with hiding the *caller's* own window if that happens afterward. Hiding
# first and accepting the small delay before the target launches is the
# version actually confirmed working.
for ($i = 0; $i -lt 20 -and -not (Hide-ThisConsole); $i++) { Start-Sleep -Milliseconds 50 }
for ($i = 0; $i -lt 5; $i++) { Start-Sleep -Milliseconds 200; Hide-ThisConsole | Out-Null }

$process = Start-Process -FilePath $Target -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -WindowStyle Minimized -PassThru
Set-Content -Path $PidFilePath -Value $process.Id -NoNewline

$process.WaitForExit()
exit $process.ExitCode
