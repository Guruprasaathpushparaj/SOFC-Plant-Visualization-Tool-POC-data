@echo off
rem Put a "SOFC Plant Twin" icon on the desktop that opens app.bat. Delete the icon to undo.
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\SOFC Plant Twin.lnk'); $s.TargetPath='%~dp0app.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0icons\icon.ico'; $s.WindowStyle=7; $s.Save()"
echo Desktop shortcut created.
