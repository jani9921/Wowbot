@echo off
setlocal
cd /d "%~dp0"
python tools\view_yolo_dataset.py "datasets\world3d_units_3class_v5"
if errorlevel 1 pause
endlocal
