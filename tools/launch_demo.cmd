@echo off
setlocal
cd /d "%~dp0.."
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -S -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 goto run_py
)
where python >nul 2>nul
if not errorlevel 1 (
  python -S -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 goto run_python
)
echo Python 3.10+ was not found on PATH. Install it, then restart VS Code.
echo For a browser-only fixture preview, open Veltrah_Demo_Offline.html.
exit /b 2
:run_py
if "%~1"=="--smoke-check" goto smoke_py
py -3 -S run_demo.py %*
exit /b %errorlevel%
:run_python
if "%~1"=="--smoke-check" goto smoke_python
python -S run_demo.py %*
exit /b %errorlevel%
:smoke_py
py -3 -S tools/smoke_demo.py
exit /b %errorlevel%
:smoke_python
python -S tools/smoke_demo.py
exit /b %errorlevel%
