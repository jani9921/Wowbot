@echo off
setlocal
cd /d "%~dp0"
rem Navigation data paths saved by INSTALL_WIZARD.bat (maps/vmaps/mmaps in _retail_).
if exist config\local_env.bat call config\local_env.bat
set "AIPC_CAPTURE_BACKEND=dxgi"
rem Screen grab in its own process: prevents GIL starvation stalls (live 2026-09-22, 2026-09-30).
if not defined AIPC_CAPTURE_PROCESS set "AIPC_CAPTURE_PROCESS=1"
if not defined AIPC_LIVE_VISION set "AIPC_LIVE_VISION=1"
if not defined AIPC_LIVE_VISION_HZ set "AIPC_LIVE_VISION_HZ=60"
if not defined AIPC_WORLD3D_PROPOSAL_MODE set "AIPC_WORLD3D_PROPOSAL_MODE=YOLO_ONLY"
if not defined AIPC_YOLO_PROCESS set "AIPC_YOLO_PROCESS=1"
where py >nul 2>nul
if errorlevel 1 goto plainpython
py -3 tools\run_agent.py --gui --with-debugger
goto done
:plainpython
python tools\run_agent.py --gui --with-debugger
:done
if errorlevel 1 pause
endlocal
