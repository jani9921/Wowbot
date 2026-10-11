@echo off
setlocal
cd /d "%~dp0"

echo WoW Screenshots - current-model proposal review
python tools\review_world3d_annotations.py "datasets\world3d_wow_screenshots_20260927_v1"
if errorlevel 1 (
  echo Annotation review failed.
  pause
  exit /b 1
)
endlocal
