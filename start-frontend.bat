@echo off
REM ===============================================================
REM  MarketLens — frontend launcher (Next.js)
REM ===============================================================
setlocal
cd /d "%~dp0frontend"

if not exist node_modules (
    echo [setup] Installing npm packages (first run)...
    call npm install || (echo npm install failed. Is Node.js installed? && pause && exit /b 1)
)

echo.
echo ===============================================================
echo  MarketLens UI running at http://localhost:3000
echo ===============================================================
echo.

call npm run dev
endlocal
