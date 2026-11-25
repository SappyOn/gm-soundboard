@echo off
REM Publishes GM Soundboard to Cloudflare Workers (*.workers.dev).
REM First run opens the browser to log in to Cloudflare.
cd /d "%~dp0"
where npx >nul 2>nul || (
  echo Node.js not found. Install it from https://nodejs.org and run this again.
  pause
  exit /b 1
)
call npx --yes wrangler@4 deploy
echo.
pause
