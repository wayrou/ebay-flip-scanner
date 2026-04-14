@echo off
setlocal

cd /d "%~dp0"

set "PYTHON=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
)

"%PYTHON%" "src\app.py"

if errorlevel 1 (
    echo.
    echo Scanner app exited with an error.
    pause
)
