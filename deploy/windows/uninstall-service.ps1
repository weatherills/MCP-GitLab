#Requires -Version 5.1
<#
.SYNOPSIS
    Stops mcp-gitlab and removes the scheduled task install-service.ps1 registered.

.PARAMETER McpGitlabPath
    Path to the mcp-gitlab executable, used to stop the running instance before the task that
    would otherwise restart it is removed. Defaults to "mcp-gitlab", resolved from PATH.

.PARAMETER TaskName
    Scheduled task name to remove. Defaults to "MCP-GitLab" (install-service.ps1's default).

.EXAMPLE
    .\uninstall-service.ps1
#>
[CmdletBinding()]
param(
    [string]$McpGitlabPath = "mcp-gitlab",
    [string]$TaskName = "MCP-GitLab"
)

$ErrorActionPreference = "Stop"

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
