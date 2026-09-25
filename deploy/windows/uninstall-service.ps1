#Requires -Version 5.1
<#
.SYNOPSIS
    Stops mcp-gitlab, removes the "MCP Servers\mcp-gitlab-server" scheduled task
    install-service.ps1 registered, and removes the Startup-folder auto-start entry.

.DESCRIPTION
    Mirrors install-service.ps1's own naming and stop logic exactly, so it reaches the same task
    and process regardless of which options install-service.ps1 was run with:

    - Calls stop-mcp-gitlab.ps1 first (not a bare Stop-ScheduledTask/Unregister-ScheduledTask):
      that alone does not reliably stop mcp-gitlab.exe itself -- see that script's own comment.
    - Removes the scheduled task with schtasks /delete, the same tool install-service.ps1 uses to
      create it (Unregister-ScheduledTask talks to a different, WMI-based provider that was found
      to fail outright with "Access is denied" on at least one managed machine -- see
      install-service.ps1's own .DESCRIPTION).
    - Removes start-mcp-gitlab-at-logon.vbs from the current account's Startup folder, the same
      way install-service.ps1 places it there.

.PARAMETER ProjectDir
    Repository root. Defaults to two levels up from this script, matching install-service.ps1 --
    pass the same -ProjectDir you gave it if you overrode that there too.

.PARAMETER Username
    Give the same -Username you passed to install-service.ps1, if you did. Needs the same elevated
    (Administrator) prompt install-service.ps1 needed for it, to remove a task registered under a
    different account. This script cannot reach that account's own Startup folder either (same
    limitation as install-service.ps1) -- it prints where to remove
    start-mcp-gitlab-at-logon.vbs from by hand.

.PARAMETER Help
    Show usage and exit. Takes no action.

.EXAMPLE
    .\uninstall-service.ps1

.EXAMPLE
    # Run elevated: removes the task registered for svc_mcpgitlab.
    .\uninstall-service.ps1 -Username "CONTOSO\svc_mcpgitlab"
#>
[CmdletBinding()]
param(
    [string]$ProjectDir = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$Username,
    [Alias("h")]
    [switch]$Help,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Extra
)

function Show-Usage {
    Write-Host @"
Usage: uninstall-service.ps1 [-ProjectDir <path>] [-Username <account>] [-Help]

Stops mcp-gitlab, removes the "MCP Servers\mcp-gitlab-server" scheduled task
install-service.ps1 registered, and removes the Startup-folder auto-start entry.

  -ProjectDir <path>   Repository root (default: two levels up from this script).
  -Username <account>  Give the same -Username you passed to install-service.ps1, if you did.
                       Needs an elevated (Administrator) prompt.
  -Help                Show this message and exit; take no action.

Examples:
  .\uninstall-service.ps1
  .\uninstall-service.ps1 -Username "CONTOSO\svc_mcpgitlab"

Full parameter documentation: Get-Help .\uninstall-service.ps1 -Full
"@
}

if ($Help -or $Extra) {
    Show-Usage
    exit 0
}

if ($Username) {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $isAdmin = ([Security.Principal.WindowsPrincipal]$currentIdentity).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Error "-Username needs an elevated (Run as Administrator) PowerShell prompt: Windows requires that to remove a task registered under an account other than the one running this script."
        exit 1
    }
}

$TaskFolder = "MCP Servers"
$TaskName = if ($Username) { "mcp-gitlab-server ($Username)" } else { "mcp-gitlab-server" }
$TaskFullName = "$TaskFolder\$TaskName"
$StartupVbsTarget = Join-Path ([Environment]::GetFolderPath("Startup")) "start-mcp-gitlab-at-logon.vbs"
$StopScript = Join-Path $PSScriptRoot "stop-mcp-gitlab.ps1"

if (Test-Path $StopScript) {
    & $StopScript -ProjectDir $ProjectDir
} else {
    Write-Warning "stop-mcp-gitlab.ps1 not found at $StopScript -- skipping the stop step and going straight to removing the task."
}

schtasks /delete /tn $TaskFullName /f 2>&1 | Out-Null

if ($Username) {
    Write-Host "Removed scheduled task '$TaskFullName'. This account's own Startup folder still has"
    Write-Host "start-mcp-gitlab-at-logon.vbs -- remove it by hand (this script cannot reach another"
    Write-Host "account's profile):"
    Write-Host "  Target (on $Username's machine, signed in as them): shell:startup"
} else {
    Remove-Item $StartupVbsTarget -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskFullName' and its Startup-folder auto-start entry."
}
