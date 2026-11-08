@echo off
REM ===============================================================
REM  MarketLens — backend launcher (FastAPI + SQLite)
REM ===============================================================
setlocal
cd /d "%~dp0backend"

REM Prefer the Python launcher (py) on Windows; fall back to bare `python`.
where py >nul 2>nul && set "PY=py" || set "PY=python"

if not exist .venv (
    echo [setup] Creating Python virtualenv with %PY%...
    %PY% -m venv .venv || (echo Failed to create venv. Is Python installed? && pause && exit /b 1)
)

call .venv\Scripts\activate.bat

echo [setup] Installing/upgrading Python dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install -r requirements.txt || (echo pip install failed. && pause && exit /b 1)

if not exist ..\.env (
    echo [setup] No .env found — copying .env.example
    copy ..\.env.example ..\.env >nul
)

echo.
echo ===============================================================
echo  MarketLens backend running at http://localhost:8000
echo  Interactive API docs:        http://localhost:8000/docs
echo ===============================================================
echo.

.venv\Scripts\python.exe run.py
endlocal
