@echo off
rem ============================================================
rem  ImageView Windows updater (double-click entry).
rem  The real work lives in update.ps1. This wrapper only:
rem    - switches the console to UTF-8 so Chinese output is readable
rem    - picks Windows PowerShell 5.1 (fallback: PowerShell 7+)
rem    - keeps the window open at the end, so both success details
rem      and failure reasons stay readable
rem  Keep this file ASCII + CRLF.
rem ============================================================
setlocal
chcp 65001 >nul 2>nul
title ImageView Update
cd /d "%~dp0"

rem Prefer the built-in Windows PowerShell by full path so a broken PATH
rem does not stop the updater; fall back to whatever is on PATH, then pwsh.
set "PS_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS_EXE%" (
    set "PS_EXE=powershell.exe"
    where powershell.exe >nul 2>nul
    if errorlevel 1 (
        set "PS_EXE=pwsh.exe"
        where pwsh.exe >nul 2>nul
        if errorlevel 1 set "PS_EXE="
    )
)
if not defined PS_EXE (
    echo PowerShell was not found on this system.
    echo Install Windows PowerShell 5.1 or PowerShell 7+ and try again.
    echo Press any key to close this window.
    pause >nul
    endlocal & exit /b 1
)

"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo Update failed with exit code %RC%.
    echo Read the message above, then press any key to close this window.
    pause >nul
    endlocal & exit /b %RC%
)

echo Update finished. Press any key to close this window.
pause >nul
endlocal & exit /b 0
