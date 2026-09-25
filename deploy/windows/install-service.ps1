#Requires -Version 5.1
<#
.SYNOPSIS
    Registers mcp-gitlab serve as a Windows Scheduled Task that starts at logon and restarts
    automatically if it exits unexpectedly. No elevated (Administrator) prompt needed for the
    default case (installing for yourself).

.DESCRIPTION
    There is no system-wide Windows service here (that needs LocalSystem context and a service
    wrapper) -- this is a per-user scheduled task, appropriate for a local single-operator MCP
    server bound to 127.0.0.1.

    Restart-on-failure is handled by Task Scheduler itself (RestartCount / RestartInterval): if
    the mcp-gitlab process exits with a non-zero code (an unhandled exception, for example), the
    task is relaunched up to RestartCount times, RestartInterval apart. ExecutionTimeLimit is set
    to zero (unlimited) since Task Scheduler otherwise kills a task after 3 days by default --
    fatal for a server meant to run indefinitely.

    Uses schtasks.exe (an XML definition + /create), not the ScheduledTasks PowerShell module's
    Register-ScheduledTask, deliberately: found live on a managed machine that
    Register-ScheduledTask (which talks to the newer WMI-based PS_ScheduledTask provider) failed
    there with a flat "Access is denied", while schtasks.exe -- which talks to the same classic
    COM-based Task Scheduler API the Task Scheduler GUI itself uses -- worked immediately, same
    account, same session, no elevation. Since schtasks.exe works everywhere the WMI path also
    would, there's no downside to always using it. (This is the actual fix for "a window opens
    then immediately closes with no output" when starting the task on demand, and for
    Register-ScheduledTask's own "No mapping between account names and security IDs was done" --
    both were symptoms of the WMI-based path, not of this task definition itself.)

    The default task is registered with NO trigger of its own -- bisecting the same "Access is
    denied" live turned up something more specific: a task registration succeeds with an explicit
    Principal/UserId/RunLevel, a full RestartOnFailure Settings block, even *starting* the task on
    demand -- everything works, except adding a LogonTrigger specifically, which alone reproduces
    the Access Denied. Almost certainly a security policy on such a machine blocking
    auto-start-at-logon registration in particular, since that's a classic persistence technique
    -- not a general Task Scheduler restriction. The workaround is start-mcp-gitlab-at-logon.vbs,
    copied into the current user's Startup folder below: a completely separate, unrestricted
    auto-start mechanism that just runs `schtasks /run` on this (trigger-less) task once at logon.
    Task Scheduler's own RestartOnFailure then keeps the task running/restarting from then on
    regardless of what started that particular run -- it isn't tied to the trigger. (-AtStartup
    below is the one case that still needs a real trigger and elevation: SYSTEM has no logon of
    its own for a Startup-folder item to piggyback on.)

    The launch is routed through run-minimized.ps1 so mcp-gitlab's console window starts
    minimized instead of popping up at logon -- see that script's own comment for why it also has
    to wait and forward the real exit code, not just launch and exit. Stopping the task alone does
    not reliably stop mcp-gitlab.exe itself, though -- a bare Stop-ScheduledTask was found live to
    leave it running, orphaned; use stop-mcp-gitlab.ps1 (which this script also calls internally,
    before re-registering) to actually stop the server, not Stop-ScheduledTask directly.

    The task is registered inside a Task Scheduler folder named "MCP Servers" (not directly in the
    root Task Scheduler Library) so it has somewhere to sit alongside other MCP servers, present
    or future, without cluttering the root list. Its full name for schtasks.exe and the
    Start-ScheduledTask/Stop-ScheduledTask/Get-ScheduledTaskInfo cmdlets (still fine to use for
    these read/start/stop operations -- the Access Denied above was specific to registering a
    LogonTrigger) is "MCP Servers\mcp-gitlab-server" (or "MCP Servers\mcp-gitlab-server
    (<Username>)" when -Username names an account other than yours, so installing for several
    accounts on one machine doesn't collide).

.PARAMETER ProjectDir
    Repository root. Defaults to two levels up from this script (this script lives in
    deploy\windows\), which is where `.venv\Scripts\mcp-gitlab.exe` and the task's pid/log files
    live by convention. Pass this explicitly if you've moved the script out of the repository.

.PARAMETER McpGitlabPath
    Path to the mcp-gitlab executable. Defaults to `.venv\Scripts\mcp-gitlab.exe` under
    -ProjectDir; falls back to PATH if that doesn't exist.

.PARAMETER Username
    Register the task to run as this account instead of yours -- for when the person installing
    this isn't the person (or service account) it should run as. Unlike the default case, this
    DOES need an elevated (Administrator) prompt: Windows requires that to register a task under
    an account other than the one running this script, regardless of which API does the
    registering. No password is stored either way -- the task still has no trigger of its own,
    same as the default case.

    [Environment]::GetFolderPath("Startup") always resolves to the CALLING account's own Startup
    folder, not -Username's -- there is no reliable way to place a file in another account's
    profile from here. This script prints the Startup-folder VBS's path and tells you to copy it
    into -Username's own Startup folder by hand (sign in as them and use `shell:startup`, or
    reach their profile over a share, e.g. \\<machine>\C$\Users\<user>\AppData\Roaming\Microsoft\
    Windows\Start Menu\Programs\Startup) instead of guessing at it.

.PARAMETER AtStartup
    Trigger the task at system startup instead of at a logon, running as SYSTEM. Unlike the
    default case, this needs an elevated (Administrator) prompt and a real trigger (a BootTrigger,
    registered the same schtasks.exe way as everything else here) -- SYSTEM has no logon of its
    own for a Startup-folder item to piggyback on, and BootTrigger wasn't implicated in the
    LogonTrigger-specific Access Denied finding above. Mutually exclusive with -Username.

.PARAMETER Help
    Show usage and exit. Takes no action.

.EXAMPLE
    .\install-service.ps1

.EXAMPLE
    .\install-service.ps1 -AtStartup

.EXAMPLE
    # Run elevated: registers the task for svc_mcpgitlab, not whoever runs this command.
    .\install-service.ps1 -Username "CONTOSO\svc_mcpgitlab"
#>
[CmdletBinding()]
param(
    [string]$ProjectDir = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$McpGitlabPath,
    [string]$Username,
    [switch]$AtStartup,
    [Alias("h")]
    [switch]$Help,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Extra
)

function Show-Usage {
    Write-Host @"
Usage: install-service.ps1 [-ProjectDir <path>] [-McpGitlabPath <path>] [-Username <account>] [-AtStartup] [-Help]

Registers mcp-gitlab serve as a Windows Scheduled Task that starts at your next logon and
restarts automatically if it exits unexpectedly. No elevated (Administrator) prompt needed for
the default case (installing for yourself).

  -ProjectDir <path>     Repository root (default: two levels up from this script).
  -McpGitlabPath <path>  Path to the mcp-gitlab executable (default: .venv\Scripts\mcp-gitlab.exe
                         under -ProjectDir, then PATH).
  -Username <account>    Register the task for this account instead of yours. Needs an elevated
                         (Administrator) prompt; see Get-Help -Full for the Startup-folder caveat.
  -AtStartup             Trigger at system startup instead of logon, running as SYSTEM. Needs an
                         elevated (Administrator) prompt. Mutually exclusive with -Username.
  -Help                  Show this message and exit; take no action.

Examples:
  .\install-service.ps1
  .\install-service.ps1 -AtStartup
  .\install-service.ps1 -Username "CONTOSO\svc_mcpgitlab"

Full parameter documentation: Get-Help .\install-service.ps1 -Full
"@
}

if ($Help -or $Extra) {
    Show-Usage
    exit 0
}

if ($AtStartup -and $Username) {
    Write-Error "-Username and -AtStartup are mutually exclusive: -AtStartup already runs as SYSTEM, independent of any user."
    exit 1
}

if ($AtStartup -or $Username) {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $isAdmin = ([Security.Principal.WindowsPrincipal]$currentIdentity).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Error "-AtStartup and -Username both need an elevated (Run as Administrator) PowerShell prompt: Windows requires that to register a task under an account other than the one running this script."
        exit 1
    }
}

$TaskFolder = "MCP Servers"
$TaskName = if ($Username) { "mcp-gitlab-server ($Username)" } else { "mcp-gitlab-server" }
$TaskFullName = "$TaskFolder\$TaskName"
$StartupVbsSource = Join-Path $PSScriptRoot "start-mcp-gitlab-at-logon.vbs"
$StartupFolder = [Environment]::GetFolderPath("Startup")
$StartupVbsTarget = Join-Path $StartupFolder "start-mcp-gitlab-at-logon.vbs"
$StopScript = Join-Path $PSScriptRoot "stop-mcp-gitlab.ps1"

if (-not $McpGitlabPath) {
    $projectVenvExe = Join-Path $ProjectDir ".venv\Scripts\mcp-gitlab.exe"
    if (Test-Path $projectVenvExe) {
        $McpGitlabPath = $projectVenvExe
    } else {
        $onPath = Get-Command "mcp-gitlab" -ErrorAction SilentlyContinue
        if ($onPath) {
            $McpGitlabPath = $onPath.Source
        } else {
            Write-Error "mcp-gitlab.exe not found at $projectVenvExe or on PATH -- create the venv and run 'pip install .' first, or pass -McpGitlabPath explicitly."
            exit 1
        }
    }
}

$RunMinimizedScript = Join-Path $PSScriptRoot "run-minimized.ps1"
if (-not (Test-Path $RunMinimizedScript)) {
    throw "run-minimized.ps1 not found at $RunMinimizedScript -- this should ship alongside install-service.ps1"
}
if (-not (Test-Path $StartupVbsSource)) {
    throw "start-mcp-gitlab-at-logon.vbs not found at $StartupVbsSource -- this should ship alongside install-service.ps1"
}
if (-not (Test-Path $StopScript)) {
    throw "stop-mcp-gitlab.ps1 not found at $StopScript -- this should ship alongside install-service.ps1"
}

$DataDir = Join-Path $ProjectDir "data"
if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir | Out-Null
}
if ($Username) {
    # $DataDir is under $ProjectDir, normally the installer's own tree -- grant the account the
    # task will actually run as write access to it, or it can't create its own pid/log files.
    icacls $DataDir /grant "${Username}:(OI)(CI)M" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "icacls could not grant $Username access to $DataDir (exit $LASTEXITCODE) -- check the account name is correct."
        exit 1
    }
}
$PidFilePath = Join-Path $DataDir "mcp-gitlab.pid"

$ArgumentString = "serve"

$ConhostExe = Join-Path $env:WINDIR "System32\conhost.exe"
$PowerShellExe = (Get-Command powershell.exe).Source
# Routed through conhost.exe --headless, not powershell.exe directly -- found live: on a machine
# with Windows Terminal set as the default terminal application, launching powershell.exe directly
# (even with -WindowStyle Hidden, and even with run-minimized.ps1's own explicit
# GetConsoleWindow+ShowWindow(SW_HIDE) call) still gets a real, visible Windows Terminal *tab* --
# confirmed by a screenshot of the actual tab. That's a separate UI surface from the legacy Win32
# console window -WindowStyle/ShowWindow control, so hiding the legacy window (which those calls
# genuinely do) doesn't stop Windows from also opening a Terminal tab for it. conhost.exe
# --headless explicitly specifies the classic console host instead of leaving Windows to resolve a
# "default terminal" for a bare powershell.exe launch, which is what triggers the adoption into
# Terminal in the first place -- confirmed live this produces zero visible window AND no new
# Windows Terminal window/tab, while the wrapped command still runs normally.
$WrapperArguments = "--headless `"$PowerShellExe`" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunMinimizedScript`" " +
    "-Target `"$McpGitlabPath`" -Arguments `"$ArgumentString`" -WorkingDirectory `"$ProjectDir`" -PidFilePath `"$PidFilePath`""

if (-not $currentIdentity) {
    # Only computed above inside the elevation check; needed here too when neither -AtStartup nor
    # -Username was given.
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
}
$UserId = if ($Username) { $Username } else { $currentIdentity.Name }

# schtasks.exe's XML import is picky about the file actually being the encoding it declares --
# UTF-16LE with a BOM, matching what Windows' own "Export Task..." produces.
# [System.IO.File]::WriteAllText with Encoding.Unicode writes exactly that; Out-File/Set-Content
# have been unreliable for this in past testing (confirmed to sometimes silently write UTF-8
# instead despite an explicit -Encoding, at least in some environments), so this deliberately uses
# neither.
#
# <Triggers></Triggers> is deliberately empty for the default and -Username cases -- see the
# .DESCRIPTION above for why a LogonTrigger specifically breaks registration on a managed machine.
# start-mcp-gitlab-at-logon.vbs (copied into the Startup folder below) is what actually starts
# this task at logon instead. -AtStartup is the exception: SYSTEM has no logon of its own, so it
# gets a real BootTrigger.
$triggersXml = if ($AtStartup) { "<BootTrigger><Enabled>true</Enabled></BootTrigger>" } else { "" }
$logonType = if ($AtStartup) { "ServiceAccount" } else { "InteractiveToken" }
$runLevel = if ($AtStartup) { "Highest" } else { "LeastPrivilege" }

$TaskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>$UserId</Author>
    <Description>mcp-gitlab MCP server -- restarts on failure; started at logon by start-mcp-gitlab-at-logon.vbs in the Startup folder, not a trigger on this task itself (except -AtStartup, which uses a real BootTrigger)</Description>
    <URI>\$TaskFullName</URI>
  </RegistrationInfo>
  <Triggers>$triggersXml</Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$UserId</UserId>
      <LogonType>$logonType</LogonType>
      <RunLevel>$runLevel</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>true</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <DisallowStartOnRemoteAppSession>false</DisallowStartOnRemoteAppSession>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$ConhostExe</Command>
      <Arguments>$WrapperArguments</Arguments>
      <WorkingDirectory>$ProjectDir</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

# Stop any instance already running under the OLD definition first -- stop-mcp-gitlab.ps1, not a
# bare Stop-ScheduledTask, because that alone does not reach mcp-gitlab.exe itself (see
# run-minimized.ps1's own comment). Left alone, re-running this script would silently leave an
# orphaned old-version process behind on every update, with a second (new-version) one now also
# running alongside it, fighting over the port.
& $StopScript -ProjectDir $ProjectDir
Start-Sleep -Seconds 1

$TempXmlPath = Join-Path ([System.IO.Path]::GetTempPath()) "mcp-gitlab-server-task.xml"
[System.IO.File]::WriteAllText($TempXmlPath, $TaskXml, [System.Text.Encoding]::Unicode)

try {
    $createOutput = schtasks /create /tn $TaskFullName /xml $TempXmlPath /f 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks /create failed (exit $LASTEXITCODE): $createOutput"
    }
} finally {
    Remove-Item $TempXmlPath -ErrorAction SilentlyContinue
}

if ($Username) {
    Write-Host "Registered '$TaskFullName' to run as $Username. This account's own Startup folder"
    Write-Host "needs start-mcp-gitlab-at-logon.vbs too -- copy it there by hand (this script"
    Write-Host "cannot reach another account's profile):"
    Write-Host "  Source: $StartupVbsSource"
    Write-Host "  Target (on $Username's machine, signed in as them): shell:startup"
} else {
    Copy-Item $StartupVbsSource $StartupVbsTarget -Force
}

schtasks /run /tn $TaskFullName | Out-Null
Start-Sleep -Seconds 2
$queryOutput = schtasks /query /tn $TaskFullName /fo list /v 2>&1 | Out-String
$lastResultMatch = [regex]::Match($queryOutput, "(?m)^Last Result:\s*(.+)$")
$lastResult = if ($lastResultMatch.Success) { $lastResultMatch.Groups[1].Value.Trim() } else { "unknown" }

Write-Host "Registered and started scheduled task '$TaskFullName'. Last Result=$lastResult"
if (-not $Username) {
    Write-Host "Will start automatically at your next logon (via the Startup folder, not a Task Scheduler trigger -- see this script's own .DESCRIPTION for why)."
}
Write-Host "Check status any time with: schtasks /query /tn `"$TaskFullName`" /fo list /v"
Write-Host "Stop it with: .\stop-mcp-gitlab.ps1 -ProjectDir `"$ProjectDir`""
Write-Host "Remove entirely with: .\uninstall-service.ps1$(if ($Username) { " -Username `"$Username`"" } else { "" })"
