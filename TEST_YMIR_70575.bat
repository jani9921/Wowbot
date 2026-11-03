@echo off
setlocal
cd /d "%~dp0"
echo Separate 70575 Ymir test - no agent GUI or FULL_AI will start.
echo Close the old agent GUI/Ymir. Start WoW to the login screen first.
echo The test asks you to confirm the WoW PID and stops after 120 seconds.
where py >nul 2>nul
if errorlevel 1 goto plainpython
py -3 -B tools\ymir_compat\test_candidate.py %*
goto done
:plainpython
python -B tools\ymir_compat\test_candidate.py %*
:done
echo.
echo Test finished. The generated PKT files are private; do not upload them publicly.
pause
