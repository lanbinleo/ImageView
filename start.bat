@echo off
rem Windows 双击启动：转给 run.ps1，结束后保留窗口方便看报错
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
pause
