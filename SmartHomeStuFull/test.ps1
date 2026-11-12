param(
    [Parameter(Mandatory)][string]$BaseArchive,
    [Parameter(Mandatory)][string]$ClangDirectory
)
$ErrorActionPreference = 'Stop'
$hostPython = Join-Path $PSScriptRoot '../SmartHomeHost/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $hostPython)) {
    throw 'Run SmartHomeHost/setup.ps1 before the native tests.'
}
& $hostPython (Join-Path $PSScriptRoot 'build_firmware.py') --base-archive $BaseArchive --prepare-only
if ($LASTEXITCODE -ne 0) { throw 'Firmware source preparation failed.' }
try {
    $previousSource = $env:SMARTHOME_FIRMWARE_SOURCE
    $env:SMARTHOME_FIRMWARE_SOURCE = Join-Path $PSScriptRoot '_work/config.mcc'
    & (Join-Path $PSScriptRoot 'tests/automation/run.ps1')
    & (Join-Path $PSScriptRoot 'tests/inputs/run_tests.ps1') -ClangDirectory $ClangDirectory
    & $hostPython -B (Join-Path $PSScriptRoot 'tests/serial/run_tests.py') --clang-dir $ClangDirectory
    if ($LASTEXITCODE -ne 0) { throw 'SH1 native tests failed.' }
    & (Join-Path $PSScriptRoot 'tests/servo/run_tests.ps1') -ClangDirectory $ClangDirectory
} finally {
    $env:SMARTHOME_FIRMWARE_SOURCE = $previousSource
}
