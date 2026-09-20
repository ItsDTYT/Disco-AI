@echo off
setlocal enabledelayedexpansion
title Disco-AI Bot Runner

echo ===================================================
echo               Starting Disco-AI Bot
echo ===================================================

cd /d "%~dp0"

REM 1. Check if .env exists
if not exist ".env" (
    echo [!] .env configuration file not found.
    echo [*] Creating .env from .env.example template...
    copy ".env.example" ".env" >nul
    echo.
    echo ===================================================
    echo [ACTION REQUIRED]
    echo Please open the newly created .env file in Notepad,
    echo paste your DISCORD_BOT_TOKEN and BOT_OWNER_ID,
    echo then save the file and come back here.
    echo ===================================================
    echo.
    pause
)

REM 2. Check for Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in your PATH.
    echo Please install Python 3.11+ from https://python.org or Windows Store.
    pause
    exit /b 1
)

REM 3. Setup Virtual Environment
if not exist ".venv\Scripts\python.exe" (
    echo [*] Setting up isolated Python virtual environment...
    where uv >nul 2>&1
    if %errorlevel% equ 0 (
        uv venv .venv
    ) else (
        python -m venv .venv
    )
)

REM 4. Install / Update Dependencies
echo [*] Checking dependencies...
where uv >nul 2>&1
if %errorlevel% equ 0 (
    uv pip install -r requirements.txt --quiet
) else (
    .venv\Scripts\pip install -r requirements.txt --quiet
)

REM 5. Run the Bot
echo [*] Launching bot...
echo.
.venv\Scripts\python bot.py

if %errorlevel% neq 0 (
    echo.
    echo [!] Bot exited with an error. Check the messages above.
    pause
)
