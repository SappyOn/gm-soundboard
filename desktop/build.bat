@echo off
REM Builds dist\GMSoundboard\GMSoundboard.exe  (needs Python 3.11-3.13 once, for building)
setlocal
cd /d "%~dp0"

set "PY="
for %%V in (3.12 3.13 3.11) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
  )
)
for %%V in (312 313 311) do (
  if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
)
if not defined PY (
  python -c "import sys; assert (3,10) <= sys.version_info[:2] <= (3,13)" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo Python 3.11 - 3.13 not found. Install Python 3.12 from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH" during install^), then run build.bat again.
  if not defined NOPAUSE pause
  exit /b 1
)
echo Using %PY%

if not exist .venv (
  %PY% -m venv .venv || goto :err
)
call .venv\Scripts\activate.bat || goto :err
python -m pip install --upgrade pip >nul
pip install -r requirements.txt "pyinstaller>=6.10" || goto :err

pyinstaller --noconfirm --clean --windowed ^
  --name GMSoundboard ^
  --icon icon.ico ^
  --add-data "ui;ui" ^
  --collect-data webview ^
  app.py || goto :err

REM ship the starter sounds with the program
if exist "..\web\public\sounds\starter" xcopy /E /I /Y "..\web\public\sounds\starter" "dist\GMSoundboard\sounds\starter" >nul

echo.
echo ============================================================
echo  Done:  dist\GMSoundboard\GMSoundboard.exe
echo  Copy the whole dist\GMSoundboard folder wherever you like
echo  (not into Program Files - the app saves files next to itself).
echo ============================================================
if not defined NOPAUSE pause
exit /b 0

:err
echo.
echo Build failed - see the messages above.
if not defined NOPAUSE pause
exit /b 1
