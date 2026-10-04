@echo off
setlocal
cd /d "%~dp0"

echo World3D unit relabel review
echo   1 = every unit (NPC, mob, corpse)  - always, also on quest givers
echo   3 = quest outline (glowing)        - same body again, or outlined object only
echo   5 = overhead symbol (! or ?)       - small box on the symbol only
python tools\review_world3d_annotations.py "datasets\world3d_units_v5_review" --start-unreviewed
if errorlevel 1 (
  echo Annotation review failed.
  pause
  exit /b 1
)
endlocal
