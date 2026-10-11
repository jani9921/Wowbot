@echo off
setlocal
cd /d "%~dp0"

set "GALLERY=runs\detect\output\model_reviews\exiles_1000_combined_1794_v3"
if not exist "%GALLERY%" (
    echo [ERROR] Prediction gallery not found:
    echo %CD%\%GALLERY%
    pause
    exit /b 1
)

py tools\review_prediction_gallery.py "%GALLERY%"
if errorlevel 1 pause

endlocal
