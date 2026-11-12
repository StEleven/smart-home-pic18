@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run setup.ps1 with PowerShell first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "run.py" --demo
