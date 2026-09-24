# MCP-GitLab auto-start scheduled task (direct copy from MCP-PersonalSearch, minimal renames)
<#
.SYNOPSIS
Registers mcp-gitlab serve as a Windows Scheduled Task that starts at logon
and restarts automatically if it exits unexpectedly.
.DESCRIPTION
Same method as MCP-PersonalSearch: no LogonTrigger (managed-policy Workaround),
per-user least-privilege task, conhost --headless wrapper via run-minimized.ps1,
Startup VBS starts task at logon, RestartOnFailure keeps it running.
#>
param(
    [string]$ProjectDir = (Split-Path -Parent $PSScriptRoot),
    [Nullable[int]]$Port = $null,
    [string]$ConfigPath = "config.toml",
    [switch]$Uninstall
)

$TaskFolder = "MCP Servers"
$TaskName = "mcp-gitlab-server"
$TaskFullName = "$TaskFolder\$TaskName"
$StartupVbsSource = Join-Path $PSScriptRoot "start-mcp-gitlab-at-logon.vbs"
$StartupFolder = [Environment]::GetFolderPath("Startup")
$StartupVbsTarget = Join-Path $StartupFolder "start-mcp-gitlab-at-logon.vbs"
$StopScript = Join-Path $PSScriptRoot "stop-mcp-gitlab.ps1"

if ($Uninstall) {
    & $StopScript -ProjectDir $ProjectDir
    schtasks /delete /tn $TaskFullName /f 2>&1 | Out-Null
    Remove-Item $StartupVbsTarget -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskFullName' and its Startup-folder auto-start entry."
    return
}

$McpExe = Join-Path $ProjectDir ".venv\Scripts\mcp-gitlab.exe"
if (-not (Test-Path $McpExe)) {
    throw "mcp-gitlab.exe not found at $McpExe -- create the venv and run 'pip install .' first"
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
$PidFilePath = Join-Path $DataDir "mcp-gitlab.pid"

# For mcp-gitlab: serve is the default command; config is handled by env/.env
$ArgumentString = "serve"
if ($null -ne $Port) {
    $ArgumentString = "serve --port $Port"
}

$ConhostExe = Join-Path $env:WINDIR "System32\conhost.exe"
$PowerShellExe = (Get-Command powershell.exe).Source
$WrapperArguments = "--headless `"$PowerShellExe`" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunMinimizedScript`" " +
    "-Target `"$McpExe`" -Arguments `"$ArgumentString`" -WorkingDirectory `"$ProjectDir`" -PidFilePath `"$PidFilePath`""

$UserId = "$env:USERDOMAIN\$env:USERNAME"

$TaskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>$UserId</Author>
    <Description>mcp-gitlab MCP server -- restarts on failure; started at logon by start-mcp-gitlab-at-logon.vbs in the Startup folder, not a trigger on this task itself</Description>
    <URI>\$TaskFullName</URI>
  </RegistrationInfo>
  <Triggers></Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$UserId</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
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

Copy-Item $StartupVbsSource $StartupVbsTarget -Force

schtasks /run /tn $TaskFullName | Out-Null
Start-Sleep -Seconds 2
$queryOutput = schtasks /query /tn $TaskFullName /fo list /v 2>&1 | Out-String
$lastResultMatch = [regex]::Match($queryOutput, "(?m)^Last Result:\s*(.+)$")
$lastResult = if ($lastResultMatch.Success) { $lastResultMatch.Groups[1].Value.Trim() } else { "unknown" }

Write-Host "Registered and started scheduled task '$TaskFullName'. Last Result=$lastResult"
Write-Host "Will start automatically at your next logon (via the Startup folder, not a Task Scheduler trigger)."
Write-Host "Check status: schtasks /query /tn `"$TaskFullName`" /fo list /v"
Write-Host "Remove entirely: powershell -ExecutionPolicy Bypass -File scripts\install-service.ps1 -Uninstall"
