#Requires -Version 5.1
<#
.SYNOPSIS
    Stops mcp-gitlab and removes the scheduled task install-service.ps1 registered.

.PARAMETER McpGitlabPath
    Path to the mcp-gitlab executable, used to stop the running instance before the task that
    would otherwise restart it is removed. Defaults to "mcp-gitlab", resolved from PATH.

.PARAMETER Username
    Give the same -Username you passed to install-service.ps1, if you did. It points this at the
    shared pid/log file install-service.ps1 set up for that account (its own per-user default
    location isn't reachable from here), and needs the same elevated (Administrator) prompt to
    be able to stop a process running as a different account.

.PARAMETER TaskName
    Scheduled task name to remove. Defaults to "MCP-GitLab" (or "MCP-GitLab (<Username>)" when
    -Username is given), matching install-service.ps1's own default - pass the same -TaskName
    you gave it if you overrode that there too.

.EXAMPLE
    .\uninstall-service.ps1

.EXAMPLE
    .\uninstall-service.ps1 -Username "CONTOSO\svc_mcpgitlab"
#>
[CmdletBinding()]
param(
    [string]$McpGitlabPath = "mcp-gitlab",
    [string]$Username,
    [string]$TaskName
)

$ErrorActionPreference = "Stop"

if (-not $TaskName) {
    $TaskName = if ($Username) { "MCP-GitLab ($Username)" } else { "MCP-GitLab" }
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
