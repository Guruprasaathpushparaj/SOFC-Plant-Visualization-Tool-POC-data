@echo off
rem Open the SOFC Plant Twin in its own app window (no browser bar, no server needed).
rem Build a proper file:/// link so folder names with # or % (e.g. "R&D #1 copy") still work.
set "TWIN_HTML=%~dp0index.html"
for /f "delims=" %%u in ('powershell -NoProfile -Command "([uri]$env:TWIN_HTML).AbsoluteUri"') do set "PAGE=%%u"
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
start "" "%EDGE%" --app="%PAGE%" --window-size=1500,950
