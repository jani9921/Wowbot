@echo off
setlocal
cd /d "%~dp0"

echo [1/2] Exile's Reach saved annotations
python tools\review_world3d_annotations.py "datasets\world3d_exiles_reach_500_v1" --reviewed-only
if errorlevel 1 goto :error

echo [2/2] 4K gameplay saved annotations
python tools\review_world3d_annotations.py "datasets\world3d_labeling_4k_v1" --reviewed-only
if errorlevel 1 goto :error

echo Every saved annotation set has been opened.
pause
exit /b 0

:error
echo Annotation review stopped with an error.
pause
exit /b 1
