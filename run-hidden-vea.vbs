' Launches vea_visitor_count.ps1 with no console window, for Task Scheduler.
'
' The third Run argument is True (wait for completion) and the exit code is
' passed to WScript.Quit, so Task Scheduler's Last Run Result reflects what the
' feed actually did. The previous version waited but discarded the exit code,
' so the task always reported success.
'
' The script path is derived from this file's own location, so the clone can
' live anywhere.

Dim fso, sh, base, rc
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

base = fso.GetParentFolderName(WScript.ScriptFullName)
rc = sh.Run("powershell.exe -ExecutionPolicy Bypass -NoProfile -File """ & base & "\vea_visitor_count.ps1""", 0, True)

WScript.Quit rc
