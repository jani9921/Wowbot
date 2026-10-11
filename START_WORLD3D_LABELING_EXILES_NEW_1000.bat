@echo off
setlocal
cd /d "%~dp0"
set "DATASET=datasets\world3d_exiles_reach_additional_1000_v1"

echo Exile's Reach additional 1000-frame review
echo SPACE = accept selected proposal, D = delete selected box
echo Use A only when every proposed box on the frame is correct.
echo 0-6 = change selected class, ENTER = save and go to next unreviewed frame
python tools\review_world3d_annotations.py "%DATASET%" --start-unreviewed
if errorlevel 1 (
  echo Annotation program failed.
  pause
  exit /b 1
)
endlocal
