@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 run_demo.py --open
  goto finished
)
where python >nul 2>nul
if not errorlevel 1 (
  python run_demo.py --open
  goto finished
)
echo Python 3.10 or newer was not found. Open Veltrah_Demo_Offline.html for a browser-only fixture preview.
:finished
echo.
pause
