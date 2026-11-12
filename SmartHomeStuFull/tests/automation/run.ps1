$ErrorActionPreference = 'Stop'
$taskDir = $PSScriptRoot
$projectDir = [System.IO.Path]::GetFullPath((Join-Path $taskDir '..\..'))
$sourceDir = $env:SMARTHOME_FIRMWARE_SOURCE
if (-not $sourceDir) { throw 'Use the test.ps1 entry point.' }
$vswhere = 'C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe'
$compiler = & $vswhere -latest -products '*' -find 'VC\Tools\MSVC\**\bin\Hostx64\x64\cl.exe' | Select-Object -First 1
if (-not $compiler) { throw 'MSVC C compiler not found.' }
$vcRoot = [System.IO.Path]::GetFullPath((Join-Path (Split-Path $compiler) '..\..\..'))
$sdkRoot = 'C:\Program Files (x86)\Windows Kits\10'
$sdkVersion = Get-ChildItem -LiteralPath (Join-Path $sdkRoot 'Include') -Directory | Sort-Object Name -Descending | Select-Object -First 1 -ExpandProperty Name
$env:INCLUDE = "$vcRoot\include;$sdkRoot\Include\$sdkVersion\ucrt;$sdkRoot\Include\$sdkVersion\shared;$sdkRoot\Include\$sdkVersion\um"
$env:LIB = "$vcRoot\lib\x64;$sdkRoot\Lib\$sdkVersion\ucrt\x64;$sdkRoot\Lib\$sdkVersion\um\x64"
$env:PATH = "$(Split-Path $compiler);$env:PATH"
$buildDir = Join-Path $projectDir '_build\automation_native'
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
Push-Location $buildDir
try {
    & $compiler /nologo /W4 /WX /utf-8 /std:c11 /TC /I"$taskDir\stubs" /I"$sourceDir\app" /I"$sourceDir" /Fe:automation_test.exe /Fo.\ "$sourceDir\app\home_automation.c" "$sourceDir\app\smart_home_app.c" "$taskDir\test_automation.c"
    if ($LASTEXITCODE -ne 0) { throw 'Native policy test compilation failed.' }
    & '.\automation_test.exe'
    if ($LASTEXITCODE -ne 0) { throw 'Native policy tests failed.' }
} finally { Pop-Location }
