@echo off
REM Run from source without building the .exe (after build.bat created .venv)
cd /d "%~dp0"
if not exist .venv (
  echo Run build.bat once first - it sets up the Python environment.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python app.py %*
