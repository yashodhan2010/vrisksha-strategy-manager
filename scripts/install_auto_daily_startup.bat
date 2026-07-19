@echo off
set SCRIPT_PATH=%~dp0run_auto_daily.bat
set SHORTCUT_PATH=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Vriksha Strategy Manager Auto Daily.lnk
powershell -NoProfile -ExecutionPolicy Bypass -Command "$shell = New-Object -ComObject WScript.Shell; $shortcut = $shell.CreateShortcut('%SHORTCUT_PATH%'); $shortcut.TargetPath = '%SCRIPT_PATH%'; $shortcut.WorkingDirectory = '%~dp0..'; $shortcut.Save()"
echo Installed startup shortcut:
echo %SHORTCUT_PATH%
pause
