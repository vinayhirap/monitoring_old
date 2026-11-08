@echo off
REM ===============================================================
REM  MarketLens — one-shot launcher (backend + frontend in 2 windows)
REM ===============================================================

echo Starting MarketLens backend in a new window...
start "MarketLens Backend" cmd /k "%~dp0start-backend.bat"

echo Waiting 5s for backend to bootstrap...
timeout /t 5 /nobreak >nul

echo Starting MarketLens frontend in a new window...
start "MarketLens Frontend" cmd /k "%~dp0start-frontend.bat"

echo.
echo ===============================================================
echo  Two new terminal windows have been opened.
echo  Backend:  http://localhost:8000  (docs at /docs)
echo  Frontend: http://localhost:3000
echo  Close those windows to stop the services.
echo ===============================================================
echo.
pause
