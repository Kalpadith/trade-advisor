@echo off
rem Trade Advisor dashboard launcher.
rem Starts the server in this window (close it or press Ctrl+C to stop)
rem and opens the dashboard in your default browser once it is up.
cd /d "%~dp0"
if not exist ".venv\Scripts\tadvisor.exe" (
    echo First-time setup: run these once in this folder:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -e ".[dev]"
    pause
    exit /b 1
)
start /b cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8000"
".venv\Scripts\tadvisor.exe" serve
