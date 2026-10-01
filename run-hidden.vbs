Set objShell = CreateObject("WScript.Shell")
objShell.Run "powershell.exe -ExecutionPolicy Bypass -File ""C:\Users\travis.schaben\Documents\signage\run-papercut-feed.ps1""", 0, False