@echo off
setlocal
cd /d "%~dp0"
set "DATASET=datasets\world3d_dragonflight_part11_300_v1"

if not exist "%DATASET%\review\manifest.jsonl" (
  echo Dataset is not ready: %DATASET%
  pause
  exit /b 1
)

echo Dragonflight Part 11 - 300-frame review
echo Drag with the mouse to create a box.
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
