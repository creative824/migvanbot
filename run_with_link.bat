@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\" (
    echo === התקנה ראשונית ===
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
    echo *** חסר קובץ .env ***  העתק את .env.example ל-.env והכנס BOT_TOKEN
    echo.
    pause
    exit /b 1
)

echo === מפעיל בוט + קישור חתימה ===
python tunnel_run.py
pause
