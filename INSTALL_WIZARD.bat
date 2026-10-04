@echo off
setlocal
cd /d "%~dp0"
rem Installation wizard: Python packages, addon, maps/vmaps/mmaps from the TrinityCore extractors in _retail_.
where py >nul 2>nul
if errorlevel 1 goto plainpython
py -3 tools\install_wizard.py
goto done
:plainpython
where python >nul 2>nul
if errorlevel 1 goto nopython
python tools\install_wizard.py
goto done
:nopython
echo Python nincs telepitve.
where winget >nul 2>nul
if errorlevel 1 goto manualpython
choice /c IN /m "Telepitsem most a Python 3.13-at (winget)? I=igen, N=nem"
if errorlevel 2 goto manualpython
winget install -e --id Python.Python.3.13 --scope user
echo.
echo Ha a telepites sikerult, zard be ezt az ablakot es inditsd ujra az INSTALL_WIZARD.bat-ot.
pause
goto end
:manualpython
echo Telepitsd a Python 3.13-at (python.org), a telepitoben pipald be az
echo "Add python.exe to PATH" opciot, majd inditsd ujra ezt a fajlt.
pause
goto end
:done
if errorlevel 1 pause
:end
endlocal
