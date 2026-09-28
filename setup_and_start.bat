@echo off
setlocal
cd /d "%~dp0"
if not defined VISION_PORT set "VISION_PORT=8765"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m app.seed
if errorlevel 1 goto failed
echo.
echo Open in browser: http://127.0.0.1:%VISION_PORT%/
echo LAN access: http://YOUR_SERVER_IP:%VISION_PORT%/
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port %VISION_PORT%
if errorlevel 1 goto failed
pause
exit /b 0
:failed
echo Startup failed. Check the error above.
pause
exit /b 1
