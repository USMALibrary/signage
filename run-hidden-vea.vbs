Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""C:\Users\travis.schaben\Documents\signage\vea_visitor_count.ps1""", 0, True
