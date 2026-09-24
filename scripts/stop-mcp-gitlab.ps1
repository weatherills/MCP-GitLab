<#
.SYNOPSIS
Stops the mcp-gitlab-server scheduled task AND the real mcp-gitlab process.
#>
param([string]$ProjectDir = (Split-Path -Parent $PSScriptRoot))
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
Get-CimInstance Win32_Process -Filter "Name='mcp-gitlab.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match '\bserve\b' } |
    ForEach-Object {
        Write-Host "Stopping leftover mcp-gitlab.exe (PID $($_.ProcessId))."
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Remove-Item $PidFilePath -ErrorAction SilentlyContinue
exit 0
