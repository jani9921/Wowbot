@echo off
setlocal
cd /d "%~dp0"

call START_WORLD3D_LABELING_EXILES_NEW_1000.bat
if errorlevel 1 exit /b 1
call START_WORLD3D_LABELING_MIDNIGHT_1000.bat
exit /b %errorlevel%
