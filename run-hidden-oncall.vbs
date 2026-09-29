' Launches oncall_relay.ps1 with no console window, for Task Scheduler.
'
' The third Run argument is True (wait for completion) so the PowerShell exit
' code reaches Task Scheduler's Last Run Result. With False the wrapper returns
' immediately and the task reports success even when the relay failed.
'
' The script path is derived from this file's own location, so the clone can
' live anywhere.

Dim fso, sh, base, rc
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

base = fso.GetParentFolderName(WScript.ScriptFullName)
rc = sh.Run("powershell.exe -ExecutionPolicy Bypass -NoProfile -File """ & base & "\oncall_relay.ps1""", 0, True)

WScript.Quit rc
