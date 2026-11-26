@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Install the Windows dependencies using the steps in README.md first.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" companion.py %*
