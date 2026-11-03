@echo off
setlocal
cd /d "%~dp0"
rem Navigation data paths saved by INSTALL_WIZARD.bat (maps/vmaps/mmaps in _retail_).
if exist config\local_env.bat call config\local_env.bat
rem Packet inbox binds on GUI connect. The hash-pinned Ymir listener starts with
rem the GUI, before WoW, and waits for the later authoritative PID binding.
set "AIPC_PACKET_TELEMETRY=1"
rem REV4 2026-10-30: the server/GUID composition, stated, not inferred from telemetry.
if not defined AIPC_RUNTIME_PROFILE set "AIPC_RUNTIME_PROFILE=SERVER"
set "AIPC_CAPTURE_BACKEND=dxgi"
rem Screen grab in its own process: prevents GIL starvation stalls (live 2026-09-22, 2026-09-30).
if not defined AIPC_CAPTURE_PROCESS set "AIPC_CAPTURE_PROCESS=1"
rem REV4 2026-10-30: no YOLO/World3D/live-vision defaults; the SERVER profile builds
rem no vision worker and never read them. Explicit LEGACY_VISION keeps code defaults.
where py >nul 2>nul
if errorlevel 1 goto plainpython
py -3 tools\run_agent.py --gui --with-debugger
goto done
:plainpython
python tools\run_agent.py --gui --with-debugger
:done
if errorlevel 1 pause
endlocal
