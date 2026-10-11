@echo off
setlocal
cd /d "%~dp0"
set "DATASET=datasets\world3d_gameplay_video_v1"
set "MODEL=models\world3d_annotation_assist_combined_1077_v1.pt"

if not exist "%MODEL%" (
  echo Trained annotation-assist model is missing: %MODEL%
  pause
  exit /b 1
)

python tools\propose_world3d_annotations.py "%DATASET%" --unreviewed-only --bootstrap-model "%MODEL%"
if errorlevel 1 (
  echo Proposal generation failed.
  pause
  exit /b 1
)

python tools\review_world3d_annotations.py "%DATASET%" --start-unreviewed
if errorlevel 1 (
  echo Annotation reviewer failed.
  pause
  exit /b 1
)
endlocal
