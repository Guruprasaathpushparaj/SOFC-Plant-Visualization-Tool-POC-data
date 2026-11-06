@echo off
rem SOFC twin dataset app: starts the small local server (no window, this PC only) and opens the app in its own Edge / Chrome window.
rem The server stops by itself about 40 s after the last app window is closed. Needs Node.js (https://nodejs.org).
cd /d "%~dp0"
set "PORT=8517"
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
where node >nul 2>nul || (echo Node.js is not installed or not on the PATH. Install it from https://nodejs.org and try again. & pause & exit /b 1)
curl.exe -s -m 1 http://127.0.0.1:%PORT%/api/health | findstr /c:"sofc-dataset" >nul && goto open
powershell -NoProfile -Command "Start-Process node -ArgumentList '\"%~dp0dataset_app\server.js\"' -WindowStyle Hidden"
set /a N=0
:wait
curl.exe -s -m 1 http://127.0.0.1:%PORT%/api/health | findstr /c:"sofc-dataset" >nul && goto open
set /a N+=1
if %N% geq 30 (echo The app did not start within 30 s. Port %PORT% may be in use by another program. & pause & exit /b 1)
ping -n 2 127.0.0.1 >nul
goto wait
:open
start "" "%EDGE%" --app=http://127.0.0.1:%PORT% --window-size=1440,960
