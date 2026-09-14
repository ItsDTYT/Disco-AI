@echo off
setlocal enabledelayedexpansion
title Mei Asahina Memory Sync Utility (LAN / Direct)
echo ========================================================
echo   Mei Asahina - Private Memory Sync Tool
echo   Syncs SQLite Datastore and users.md across LAN
echo ========================================================
echo.

:: Default remote machine share path (adjust IP if different)
set "REMOTE_TARGET=\\192.168.2.174\Mei"

echo Current remote target: !REMOTE_TARGET!
echo.
echo [1] PULL memories from remote PC to this PC
echo [2] PUSH memories from this PC to remote PC
echo [3] Change remote network target path
echo [4] Create local backup of memories
echo [5] Exit
echo.
set /p CHOICE="Choose an option [1-5]: "

if "%CHOICE%"=="1" goto PULL
if "%CHOICE%"=="2" goto PUSH
if "%CHOICE%"=="3" goto SET_PATH
if "%CHOICE%"=="4" goto BACKUP
if "%CHOICE%"=="5" goto EXIT
goto EXIT

:SET_PATH
echo.
set /p REMOTE_TARGET="Enter remote path (e.g. \\192.168.2.174\Mei or D:\Shared\Mei): "
echo Target updated to: !REMOTE_TARGET!
echo.
pause
goto EXIT

:PULL
echo.
echo Pulling memories from: !REMOTE_TARGET! ...
if not exist "!REMOTE_TARGET!" (
    echo [ERROR] Remote path '!REMOTE_TARGET!' not reachable.
    echo Make sure network sharing is enabled on the remote PC.
    goto END
)

:: Make backup first
call :DO_BACKUP

if exist "!REMOTE_TARGET!\data\mei_memory.db" (
    if not exist "data" mkdir "data"
    copy /y "!REMOTE_TARGET!\data\mei_memory.db" "data\mei_memory.db" >nul
    echo [OK] Copied data\mei_memory.db
)
if exist "!REMOTE_TARGET!\users.md" (
    copy /y "!REMOTE_TARGET!\users.md" "users.md" >nul
    echo [OK] Copied users.md
)
echo.
echo Memory sync (PULL) complete!
goto END

:PUSH
echo.
echo Pushing memories to: !REMOTE_TARGET! ...
if not exist "!REMOTE_TARGET!" (
    echo [ERROR] Remote path '!REMOTE_TARGET!' not reachable.
    echo Make sure the folder is shared with write permissions.
    goto END
)

if not exist "!REMOTE_TARGET!\data" mkdir "!REMOTE_TARGET!\data" 2>nul
if exist "data\mei_memory.db" (
    copy /y "data\mei_memory.db" "!REMOTE_TARGET!\data\mei_memory.db" >nul
    echo [OK] Pushed data\mei_memory.db
)
if exist "users.md" (
    copy /y "users.md" "!REMOTE_TARGET!\users.md" >nul
    echo [OK] Pushed users.md
)
echo.
echo Memory sync (PUSH) complete!
goto END

:BACKUP
call :DO_BACKUP
goto END

:DO_BACKUP
if not exist "backups" mkdir "backups"
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c-%%a-%%b)
for /f "tokens=1-2 delims=/:" %%a in ('time /t') do (set mytime=%%a%%b)
set "STAMP=%mydate%_%mytime: =0%"

if exist "data\mei_memory.db" (
    copy /y "data\mei_memory.db" "backups\mei_memory_%STAMP%.db" >nul
    echo [BACKUP] Saved backups\mei_memory_%STAMP%.db
)
if exist "users.md" (
    copy /y "users.md" "backups\users_%STAMP%.md" >nul
    echo [BACKUP] Saved backups\users_%STAMP%.md
)
exit /b

:END
echo.
pause
:EXIT
