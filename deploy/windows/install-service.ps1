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
    process for your logon session, not under the Service Control Manager / Session 0. It stops
    when you log off, same as any other per-session background process. If you need a real
    Windows Service (running with no user logged in), wrap `mcp-gitlab serve` with a
    service-hosting tool such as NSSM or `pywin32`'s win32serviceutil instead — this script
    intentionally doesn't add either as a project dependency.

.PARAMETER McpGitlabPath
    Path to the mcp-gitlab executable. Defaults to "mcp-gitlab", resolved from PATH (works once
    you've `pip install`-ed this package into an active environment).

.PARAMETER AtStartup
    Trigger the task at system startup instead of at your logon. Needs an elevated
    (Administrator) PowerShell prompt, and the server then runs under the SYSTEM account.

.PARAMETER TaskName
    Scheduled task name. Defaults to "MCP-GitLab".

.EXAMPLE
    .\install-service.ps1

.EXAMPLE
    .\install-service.ps1 -McpGitlabPath "C:\path\to\venv\Scripts\mcp-gitlab.exe" -AtStartup
#>
[CmdletBinding()]
param(
    [string]$McpGitlabPath = "mcp-gitlab",
    [switch]$AtStartup,
    [string]$TaskName = "MCP-GitLab"
)

$ErrorActionPreference = "Stop"

if ($AtStartup) {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $isAdmin = ([Security.Principal.WindowsPrincipal]$currentUser).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Error "-AtStartup needs an elevated (Run as Administrator) PowerShell prompt."
        exit 1
    }
}

$action = New-ScheduledTaskAction -Execute $McpGitlabPath -Argument "service start"
if ($AtStartup) {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
} else {
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
}
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' to run '$McpGitlabPath service start'."
Write-Host "Starting it now..."
& $McpGitlabPath service start
Write-Host "Configure the server with environment variables or a .env file next to $McpGitlabPath (see .env.example) before relying on this."
Write-Host "To remove it: .\uninstall-service.ps1"
