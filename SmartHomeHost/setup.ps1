$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create Python environment.' }
}
& '.venv/Scripts/python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed. If pip reports a long path, use a shorter checkout path.' }
& '.venv/Scripts/python.exe' -c 'from PySide6.QtWebEngineWidgets import QWebEngineView'
if ($LASTEXITCODE -ne 0) { throw 'Qt WebEngine failed to import.' }
Push-Location -LiteralPath 'frontend'
try {
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
Write-Output 'Ready. Open the launcher .cmd, or run ./.venv/Scripts/python.exe run.py --demo'
