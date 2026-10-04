@echo off
setlocal
cd /d "%~dp0"
rem Navigation data paths saved by INSTALL_WIZARD.bat (maps/vmaps/mmaps in _retail_).
if exist config\local_env.bat call config\local_env.bat

rem Do not start a second controller beside an already running agent.
powershell -NoProfile -Command "$running = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'tools[\\/]run_agent\.py' }; if ($running) { exit 1 }"
if errorlevel 1 (
    echo An AIPC agent is already running. Close its GUI first, then run this file again.
    pause
    exit /b 2
)

rem Force Live Vision on even if the parent environment disabled it.
set "AIPC_CAPTURE_BACKEND=dxgi"
rem Screen grab in its own process: prevents GIL starvation stalls (live 2026-09-22, 2026-09-30).
if not defined AIPC_CAPTURE_PROCESS set "AIPC_CAPTURE_PROCESS=1"
set "AIPC_LIVE_VISION=1"
set "AIPC_LIVE_VISION_HZ=60"
set "AIPC_LIVE_VISION_OPENCV_THREADS=1"
set "AIPC_WORLD3D_PROPOSAL_MODE=YOLO_ONLY"
set "AIPC_YOLO_PROCESS=1"

where py >nul 2>nul
if errorlevel 1 goto plainpython
py -3 tools\run_agent.py --gui --with-debugger
goto done

:plainpython
python tools\run_agent.py --gui --with-debugger

:done
if errorlevel 1 pause
endlocal
