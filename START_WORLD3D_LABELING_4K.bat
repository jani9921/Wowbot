@echo off
setlocal
cd /d "%~dp0"
set "DATASET=datasets\world3d_labeling_4k_v1"

if not exist "%DATASET%\review\images" (
  echo The labeling image folder is missing: %DATASET%\review\images
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
