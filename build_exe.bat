@echo off
cd /d "%~dp0"
python -m pip install --user -q pyinstaller
python build_exe.py %*
echo.
echo Done: dist\ImageAnnotator.exe
pause
