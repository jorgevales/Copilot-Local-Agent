@echo off
powershell -NoProfile -File "%~dp0Launcher.ps1" -Mode Start
set "agent_result=%errorlevel%"
pause
exit /b %agent_result%
