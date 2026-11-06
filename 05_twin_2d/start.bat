@echo off
rem Serve the SOFC Plant Twin at http://localhost:8765 and open it in the browser.
cd /d "%~dp0"
start "" http://localhost:8765/index.html
python -m http.server 8765
