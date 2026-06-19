@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-dashboard.ps1" -AutoStartAgents
pause
