# MCP-GitLab auto-start scheduled task (LogonTrigger direct, per-user, no admin)
param($ProjectDir=(Split-Path -Parent $PSScriptRoot),$Port=$null,[switch]$Uninstall)
$TaskFolder="MCP Servers"; $TaskName="mcp-gitlab-server"; $TaskFullName="$TaskFolder\$TaskName"
if($Uninstall){ schtasks /delete /tn $TaskFullName /f 2>&1|Out-Null; exit 0 }
$Exe=Join-Path $ProjectDir ".venv\Scripts\mcp-gitlab.exe"
$Xml=@"<?xml version="1.0" encoding="UTF-16"?><Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><RegistrationInfo><Author>$env:USERNAME</Author></RegistrationInfo><Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers><Principals><Principal id="A"><UserId>$env:USERDOMAIN\$env:USERNAME</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals><Settings><RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy></Settings><Actions Context="A"><Exec><Command>$Exe</Command><Arguments>serve</Arguments><WorkingDirectory>$ProjectDir</WorkingDirectory></Exec></Actions></Task>"@
$tmp=Join-Path $env:TEMP "mcp-gitlab-task.xml"; [System.IO.File]::WriteAllText($tmp,$Xml,[System.Text.Encoding]::Unicode)
schtasks /create /tn $TaskFullName /xml $tmp /f; Remove-Item $tmp -ErrorAction SilentlyContinue; schtasks /run /tn $TaskFullName | Out-Null
Write-Host "Registered $TaskFullName with LogonTrigger."
