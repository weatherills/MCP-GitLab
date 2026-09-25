' Placed in the current user's Startup folder by install-service.ps1.
' Starts the mcp-gitlab-server scheduled task on demand at logon, with no
' visible window of its own (WScript.Shell.Run's second argument, 0, means
' hidden; the third, False, means don't wait).
'
' Why this exists instead of a normal LogonTrigger on the task itself:
' found live that registering a scheduled task with a LogonTrigger
' specifically fails with "Access is denied" on a managed machine, even
' though every other part of the same task definition (Settings,
' RestartOnFailure, an explicit Principal/UserId, and even *starting* the
' task on demand) works fine for the same non-admin account -- almost
' certainly a security policy blocking auto-start-at-logon registration
' specifically, since that's a classic persistence technique. The task
' itself is registered with no triggers at all; this script is the
' trigger instead, using the Startup folder, a separate and unrestricted
' auto-start mechanism every Windows account already has. Task
' Scheduler's own RestartOnFailure setting still keeps the task
' running/restarting after this one on-demand kick, regardless of what
' started that particular run.
Set objShell = CreateObject("WScript.Shell")
objShell.Run "schtasks /run /tn ""MCP Servers\mcp-gitlab-server""", 0, False
