@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launcher.ps1" -Mode UI
set "agent_result=%errorlevel%"
pause
exit /b %agent_result%
