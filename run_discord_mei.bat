@echo off
setlocal
title Mei Asahina Discord Bot
echo ========================================================
echo   Starting Mei Asahina Discord Bot
echo ========================================================
echo.

cd /d "%~dp0"

:: Check if .venv exists in root, bootstrap if missing
if not exist ".venv\Scripts\activate.bat" (
    echo [SETUP] Virtual environment not found in root. Creating .venv...
    where uv >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        echo [SETUP] Using uv for fast environment creation...
        uv venv
        call .venv\Scripts\activate.bat
        uv pip install -r requirements.txt
    ) else (
        echo [SETUP] Using standard python venv...
        python -m venv .venv
        call .venv\Scripts\activate.bat
        python -m pip install --upgrade pip
        pip install -r requirements.txt
    )
    echo [SETUP] Setup complete!
    echo.
) else (
    call .venv\Scripts\activate.bat
)

:: Launch the bot
python discord_mei.py
if %ERRORLEVEL% neq 0 (
    echo.
    echo Bot stopped with exit code %ERRORLEVEL%.
)
pause
