@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launcher.ps1" -Mode Setup
set "agent_result=%errorlevel%"
pause
exit /b %agent_result%
