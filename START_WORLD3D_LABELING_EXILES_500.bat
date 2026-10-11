@echo off
setlocal
cd /d "%~dp0"
set "DATASET=datasets\world3d_exiles_reach_500_v1"

if not exist "%DATASET%\review\images" (
  echo The Exile's Reach labeling image folder is missing: %DATASET%\review\images
  pause
  exit /b 1
)

python tools\review_world3d_annotations.py "%DATASET%" --start-unreviewed
if errorlevel 1 (
  echo Annotation program failed.
  pause
  exit /b 1
)
endlocal
