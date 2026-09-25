#Requires -Version 5.1
<#
.SYNOPSIS
    Registers a Windows Scheduled Task that runs `mcp-gitlab service start` automatically.

.DESCRIPTION
    A courtesy for Windows users who are not using the Linux/Docker deployment this project is
    built for (see the main README and CLAUDE.md). It wraps `mcp-gitlab service start/stop`
    (OS-independent already) in Windows' own Task Scheduler, so the server comes back after a
    logon without you having to run the command yourself.

    This is NOT a true Windows Service: the task runs `mcp-gitlab` as a normal background
    process for a logon session, not under the Service Control Manager / Session 0. It stops
    when that user logs off, same as any other per-session background process. If you need a
    real Windows Service (running with no user logged in), wrap `mcp-gitlab serve` with a
    service-hosting tool such as NSSM or `pywin32`'s win32serviceutil instead - this script
    intentionally doesn't add either as a project dependency.

.PARAMETER McpGitlabPath
    Path to the mcp-gitlab executable. If omitted, this looks first on PATH, then for a venv at
    the repository's own conventional location relative to this script
    (..\..\.venv\Scripts\mcp-gitlab.exe - i.e. a `.venv` at the repository root, created per
    CLAUDE.md's "Running things"). Neither may be right for -Username's account (PATH reflects
    whoever runs this script, not the account the task will run as, and a relative guess can be
    wrong), so pass this explicitly whenever you're not sure it'll resolve for that account.

.PARAMETER Username
    Register the task to run as this account instead of yours - for when the person installing
    this isn't the person (or service account) it should run as. Give it as Task Scheduler
    expects: "DOMAIN\user", ".\user" for a local account, or a bare name it can resolve locally.
    No password is needed or stored: the task triggers on THAT account's own logon and runs
    inside their session (same "stops at logoff" model as the default, just for a different
    account) - but registering a task to run as anyone other than yourself needs an elevated
    (Administrator) prompt, since Windows requires that regardless of logon type.

    Because the target account's own per-user default pid/log file location (see service.py)
    isn't reachable from here, using -Username points both accounts at a shared location instead
    (%ProgramData%\mcp-gitlab) and grants that account write access to it - see the README in
    this directory for the mechanism, and confirm it in your environment: this path is exercised
    far less than the rest of the codebase.

.PARAMETER AtStartup
    Trigger the task at system startup instead of at a logon. Needs an elevated (Administrator)
    prompt, and the server then runs under the SYSTEM account. Mutually exclusive with -Username:
    SYSTEM is already independent of whoever's logged on, so naming another account isn't
    meaningful here.

.PARAMETER TaskName
    Scheduled task name. Defaults to "MCP-GitLab", or "MCP-GitLab (<Username>)" when -Username is
    given and this isn't set explicitly - so installing for several accounts on one machine
    doesn't silently overwrite an earlier registration.

.PARAMETER Help
    Show usage and exit. Takes no action. (Run with no arguments at all does the same - this
    script never installs anything without at least one argument telling it to.)

.EXAMPLE
    .\install-service.ps1 -TaskName "MCP-GitLab"

.EXAMPLE
    .\install-service.ps1 -McpGitlabPath "C:\path\to\venv\Scripts\mcp-gitlab.exe" -AtStartup

.EXAMPLE
    # Run elevated: registers the task for svc_mcpgitlab, not whoever runs this command.
    .\install-service.ps1 -Username "CONTOSO\svc_mcpgitlab" `
        -McpGitlabPath "C:\Users\svc_mcpgitlab\mcp-gitlab\.venv\Scripts\mcp-gitlab.exe"
#>
[CmdletBinding()]
param(
    [string]$McpGitlabPath,
    [string]$Username,
    [switch]$AtStartup,
    [string]$TaskName,
    [Alias("h")]
    [switch]$Help,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Extra
)

function Show-Usage {
    Write-Host @"
Usage: install-service.ps1 [-McpGitlabPath <path>] [-Username <account>] [-AtStartup] [-TaskName <name>] [-Help]

Registers a Windows Scheduled Task that runs 'mcp-gitlab service start' automatically at your
next logon (or at system startup, as SYSTEM, with -AtStartup).

  -McpGitlabPath <path>  Path to the mcp-gitlab executable (auto-detected if omitted: PATH,
                         then ..\..\.venv\Scripts\mcp-gitlab.exe relative to this script).
  -Username <account>    Register the task for this account instead of yours. No password
                         needed, but needs an elevated (Administrator) prompt.
  -AtStartup             Trigger at system startup instead of logon, running as SYSTEM. Needs
                         an elevated (Administrator) prompt. Mutually exclusive with -Username.
  -TaskName <name>       Scheduled task name (default: "MCP-GitLab", or "MCP-GitLab (<Username>)").
  -Help                  Show this message and exit; take no action.

Examples:
  .\install-service.ps1 -TaskName "MCP-GitLab"
  .\install-service.ps1 -AtStartup
  .\install-service.ps1 -Username "CONTOSO\svc_mcpgitlab" -McpGitlabPath "C:\...\mcp-gitlab.exe"

Full parameter documentation: Get-Help .\install-service.ps1 -Full
"@
}

if ($Help -or $Extra -or $PSBoundParameters.Count -eq 0) {
    Show-Usage
    exit 0
}

$ErrorActionPreference = "Stop"

$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]$currentIdentity).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

if ($AtStartup -and $Username) {
    Write-Error "-Username and -AtStartup are mutually exclusive: -AtStartup already runs as SYSTEM, independent of any user."
    exit 1
}
if (-not $TaskName) {
    $TaskName = if ($Username) { "MCP-GitLab ($Username)" } else { "MCP-GitLab" }
}
if (($AtStartup -or $Username) -and -not $isAdmin) {
    Write-Error "-AtStartup and -Username both need an elevated (Run as Administrator) PowerShell prompt: Windows requires that to register a task under an account other than the one running this script."
    exit 1
}

if (-not $McpGitlabPath) {
    # Not on PATH is common: a venv's Scripts folder is only on PATH inside an activated venv,
    # and Task Scheduler / a fresh elevated prompt starts with neither.
    $onPath = Get-Command "mcp-gitlab" -ErrorAction SilentlyContinue
    if ($onPath) {
        $McpGitlabPath = $onPath.Source
    } else {
        $venvExe = Join-Path $PSScriptRoot "..\..\.venv\Scripts\mcp-gitlab.exe"
        if (Test-Path $venvExe) {
            $McpGitlabPath = (Resolve-Path $venvExe).Path
        } else {
            Write-Error "Could not find mcp-gitlab: it isn't on PATH, and $venvExe doesn't exist. Pass -McpGitlabPath explicitly (your venv's Scripts\mcp-gitlab.exe)."
            exit 1
        }
    }
    Write-Host "Using mcp-gitlab at: $McpGitlabPath"
}

if ($Username) {
    # service.py defaults the pid/log file to the running account's own home directory, which
    # $Username's account has and yours can't see (and vice versa for whoever later stops it) -
    # point both at one shared location instead, and give $Username write access to it.
    $sharedStateDir = Join-Path $env:ProgramData "mcp-gitlab"
    New-Item -ItemType Directory -Path $sharedStateDir -Force | Out-Null
    icacls $sharedStateDir /grant "${Username}:(OI)(CI)M" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        # icacls is an external command: $ErrorActionPreference doesn't apply to its exit code.
        Write-Error "icacls could not grant $Username access to $sharedStateDir (exit $LASTEXITCODE) - check the account name is correct."
        exit 1
    }
    $pidFile = Join-Path $sharedStateDir "mcp-gitlab.pid"
    $logFile = Join-Path $sharedStateDir "service.log"
    # Machine scope so $Username's own session picks it up when the task's trigger fires there;
    # also set here so any direct use of this same prompt (e.g. Start-ScheduledTask below) agrees.
    [Environment]::SetEnvironmentVariable("MCP_GITLAB_PID_FILE", $pidFile, "Machine")
    [Environment]::SetEnvironmentVariable("MCP_GITLAB_SERVICE_LOG_FILE", $logFile, "Machine")
    $env:MCP_GITLAB_PID_FILE = $pidFile
    $env:MCP_GITLAB_SERVICE_LOG_FILE = $logFile
}

$action = New-ScheduledTaskAction -Execute $McpGitlabPath -Argument "service start"
if ($AtStartup) {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
} elseif ($Username) {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $Username
    $principal = New-ScheduledTaskPrincipal -UserId $Username -LogonType Interactive
} else {
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    # $currentIdentity.Name (not $env:USERDOMAIN\$env:USERNAME): it's read from this process's
    # own security token, so Windows already knows it maps to a real SID. The env-var version can
    # fail that lookup for some account types (e.g. a Microsoft Account) with "No mapping between
    # account names and security IDs was done".
    $principal = New-ScheduledTaskPrincipal -UserId $currentIdentity.Name -LogonType Interactive
}
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' to run '$McpGitlabPath service start'."
if ($Username) {
    Write-Host "It will start automatically the next time $Username logs on."
    Write-Host "Not starting it now: doing so here would run it as you, not as $Username."
    Write-Host "If $Username is already logged on, start it immediately with:"
    Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
} else {
    Write-Host "Starting it now..."
    & $McpGitlabPath service start
}
Write-Host "Configure the server with environment variables or a .env file next to $McpGitlabPath (see .env.example) before relying on this."
if ($Username) {
    Write-Host "To remove it: .\uninstall-service.ps1 -Username `"$Username`""
} else {
    Write-Host "To remove it: .\uninstall-service.ps1"
}
