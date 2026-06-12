@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo =========================================
echo Binance Futures Testnet Trading Bot
echo =========================================

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
) else (
    echo Virtual environment already exists.
)

call venv\Scripts\activate.bat

echo Installing Python dependencies...
pip install -r requirements.txt

if not exist .env (
    echo Copying .env.example to .env...
    copy /Y .env.example .env >nul
    echo.
    echo Please edit .env and add your Binance Testnet credentials:
    echo   BINANCE_API_KEY
    echo   BINANCE_API_SECRET
    echo.
    echo Note: Do not wrap the values in quotes. Example:
    echo   BINANCE_API_KEY=your_api_key_here
    echo   BINANCE_API_SECRET=your_api_secret_here
    echo.
    start notepad .env
    pause
) else (
    echo .env already exists.
)

echo Starting backend server in a new window...
start "Trading Bot Backend" cmd /k "call venv\Scripts\activate.bat && python -m uvicorn server:app --reload --port 8000"

echo Waiting 3 seconds for the server to start...
timeout /t 3 >nul

echo Opening frontend in your browser...
start "" http://localhost:8000/

echo.
echo Backend is launching. The browser should open automatically.
echo If it does not, open http://localhost:8000/ manually.
endlocal
