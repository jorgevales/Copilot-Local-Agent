@echo off
powershell -NoProfile -File "%~dp0Launcher.ps1" -Mode Tests
set "agent_result=%errorlevel%"
pause
exit /b %agent_result%
