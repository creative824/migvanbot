@echo off
cd /d "%~dp0"

if not exist ".venv\" (
    echo === First-time setup ===
    py -3 -m venv .venv || python -m venv .venv
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    python -m playwright install chromium
) else (
    call ".venv\Scripts\activate.bat"
)

if not exist ".env" (
    echo.
    echo *** Missing .env file ***  Copy .env.example to .env and fill in BOT_TOKEN
    echo.
    pause
    exit /b 1
)

echo === Starting the bot ===
python bot.py
pause
