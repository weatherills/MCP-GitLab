#Requires -Version 5.1
<#
.SYNOPSIS
    Stops mcp-gitlab and removes the scheduled task install-service.ps1 registered.

.PARAMETER McpGitlabPath
    Path to the mcp-gitlab executable, used to stop the running instance before the task that
    would otherwise restart it is removed. If omitted, this looks first on PATH, then for a venv
    at the repository's own conventional location relative to this script
    (..\..\.venv\Scripts\mcp-gitlab.exe). If neither resolves, the task is still removed; only
    the "stop the running process" step is skipped, with a warning.

.PARAMETER Username
    Give the same -Username you passed to install-service.ps1, if you did. It points this at the
    shared pid/log file install-service.ps1 set up for that account (its own per-user default
    location isn't reachable from here), and needs the same elevated (Administrator) prompt to
    be able to stop a process running as a different account.

.PARAMETER TaskName
    Scheduled task name to remove. Defaults to "MCP-GitLab" (or "MCP-GitLab (<Username>)" when
    -Username is given), matching install-service.ps1's own default - pass the same -TaskName
    you gave it if you overrode that there too.

.PARAMETER Help
    Show usage and exit. Takes no action. (Run with no arguments at all does the same - this
    script never stops or removes anything without at least one argument telling it to.)

.EXAMPLE
    .\uninstall-service.ps1 -TaskName "MCP-GitLab"

.EXAMPLE
    .\uninstall-service.ps1 -Username "CONTOSO\svc_mcpgitlab"
#>
[CmdletBinding()]
param(
    [string]$McpGitlabPath,
    [string]$Username,
    [string]$TaskName,
    [Alias("h")]
    [switch]$Help,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Extra
)

function Show-Usage {
    Write-Host @"
Usage: uninstall-service.ps1 [-McpGitlabPath <path>] [-Username <account>] [-TaskName <name>] [-Help]

Stops mcp-gitlab and removes the scheduled task install-service.ps1 registered.

  -McpGitlabPath <path>  Path to the mcp-gitlab executable, used to stop it first (auto-detected
                         if omitted). Not fatal if it can't be found: the task is still removed.
  -Username <account>    Give the same -Username you passed to install-service.ps1, if you did.
                         Needs an elevated (Administrator) prompt.
  -TaskName <name>       Scheduled task name to remove (default: "MCP-GitLab", or
                         "MCP-GitLab (<Username>)"); pass the same -TaskName you gave install if
                         you overrode that there too.
  -Help                  Show this message and exit; take no action.

Examples:
  .\uninstall-service.ps1 -TaskName "MCP-GitLab"
  .\uninstall-service.ps1 -Username "CONTOSO\svc_mcpgitlab"

Full parameter documentation: Get-Help .\uninstall-service.ps1 -Full
"@
}

if ($Help -or $Extra -or $PSBoundParameters.Count -eq 0) {
    Show-Usage
    exit 0
}

$ErrorActionPreference = "Stop"

if (-not $TaskName) {
    $TaskName = if ($Username) { "MCP-GitLab ($Username)" } else { "MCP-GitLab" }
}

if (-not $McpGitlabPath) {
    $onPath = Get-Command "mcp-gitlab" -ErrorAction SilentlyContinue
    if ($onPath) {
        $McpGitlabPath = $onPath.Source
    } else {
        $venvExe = Join-Path $PSScriptRoot "..\..\.venv\Scripts\mcp-gitlab.exe"
        # Not found is not fatal here (unlike install-service.ps1): the task still gets removed
        # below either way, just without a clean "service stop" first if this doesn't resolve.
        $McpGitlabPath = if (Test-Path $venvExe) { (Resolve-Path $venvExe).Path } else { "mcp-gitlab" }
    }
}

if ($Username) {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $isAdmin = ([Security.Principal.WindowsPrincipal]$currentIdentity).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Error "-Username needs an elevated (Run as Administrator) PowerShell prompt: stopping a process running as a different account needs it."
        exit 1
    }
    # Match install-service.ps1's shared location for this account instead of the per-user
    # default (service.py), which isn't reachable from here.
    $sharedStateDir = Join-Path $env:ProgramData "mcp-gitlab"
    $env:MCP_GITLAB_PID_FILE = Join-Path $sharedStateDir "mcp-gitlab.pid"
    $env:MCP_GITLAB_SERVICE_LOG_FILE = Join-Path $sharedStateDir "service.log"
}

try {
    & $McpGitlabPath service stop
} catch {
    Write-Warning "Could not stop mcp-gitlab (it may not have been running): $_"
}

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
} else {
    Write-Host "No scheduled task named '$TaskName' was found."
}
