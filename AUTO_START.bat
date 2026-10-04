@echo off
setlocal
cd /d "%~dp0"
rem Start WoW if needed, log in with config\wow_password.txt (first line),
rem enter the world and start the agent in FULL_AI (tools\wow_auto_start.py).
if exist config\local_env.bat call config\local_env.bat
where py >nul 2>nul
if errorlevel 1 goto plainpython
py -3 tools\wow_auto_start.py %*
goto done
:plainpython
python tools\wow_auto_start.py %*
:done
if errorlevel 1 pause
endlocal
