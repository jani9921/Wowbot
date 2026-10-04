@echo off
setlocal
cd /d "%~dp0"
rem Navigation data paths saved by INSTALL_WIZARD.bat (maps/vmaps/mmaps in _retail_).
if exist config\local_env.bat call config\local_env.bat
where py >nul 2>nul
if errorlevel 1 goto plainpython
py -3 tools\live_debug_monitor.py
goto done
:plainpython
python tools\live_debug_monitor.py
:done
if errorlevel 1 pause
endlocal
