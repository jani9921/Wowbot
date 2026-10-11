@echo off
setlocal
cd /d "%~dp0"

echo Live PID 8260 - 10 manually reviewed frames
python tools\review_world3d_annotations.py "datasets\world3d_live_pid8260_manual_10_v1" --reviewed-only
if errorlevel 1 (
  echo Annotation review failed.
  pause
  exit /b 1
)
endlocal
