<#
.SYNOPSIS
Launches mcp-gitlab minimized, records PID, waits for exit, forwards exit code.
#>
param(
    [Parameter(Mandatory)][string]$Target,
    [Parameter(Mandatory)][string]$Arguments,
    [Parameter(Mandatory)][string]$WorkingDirectory,
    [Parameter(Mandatory)][string]$PidFilePath
)
Add-Type @"
using System; using System.Runtime.InteropServices;
public class ConsoleWindow {
    [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@
function Hide-ThisConsole {
    $hwnd = [ConsoleWindow]::GetConsoleWindow()
    if ($hwnd -ne [IntPtr]::Zero) { [ConsoleWindow]::ShowWindow($hwnd, 0) | Out-Null; return $true }
    return $false
}
for ($i = 0; $i -lt 20 -and -not (Hide-ThisConsole); $i++) { Start-Sleep -Milliseconds 50 }
for ($i = 0; $i -lt 5; $i++) { Start-Sleep -Milliseconds 200; Hide-ThisConsole | Out-Null }
$process = Start-Process -FilePath $Target -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -WindowStyle Minimized -PassThru
Set-Content -Path $PidFilePath -Value $process.Id -NoNewline
$process.WaitForExit()
exit $process.ExitCode
