@echo off
setlocal
cd /d "%~dp0"
if not defined VISION_PORT set "VISION_PORT=8765"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup_and_start.bat first.
  pause
  exit /b 1
)
echo Open in browser: http://127.0.0.1:%VISION_PORT%/
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port %VISION_PORT%
pause
