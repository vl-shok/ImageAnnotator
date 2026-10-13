@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul && (start "" pythonw main.py %*) || (start "" python main.py %*)
