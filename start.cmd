@echo off
chcp 65001 >nul
wsl.exe --cd "%~dp0." -- bash ./start.sh
pause
