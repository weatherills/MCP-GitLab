# Start mcp-gitlab scheduled task at logon (Startup folder trigger, no LogonTrigger)
Set objShell = CreateObject("WScript.Shell")
objShell.Run "schtasks /run /tn ""MCP Servers\mcp-gitlab-server""", 0, False
