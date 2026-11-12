param(
    [Parameter(Mandatory)][string]$ClangDirectory
)
$ErrorActionPreference = 'Stop'
$sourceDir = $env:SMARTHOME_FIRMWARE_SOURCE
if (-not $sourceDir) { throw 'Use the test.ps1 entry point.' }
$buildDir = Join-Path $PSScriptRoot '.build'
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
$compiler = Join-Path $ClangDirectory 'clang.exe'
$linker = Join-Path $ClangDirectory 'lld.exe'
$includes = @(
    '-I', (Join-Path $PSScriptRoot 'stubs'),
    '-I', (Join-Path $sourceDir 'device_driver'),
    '-I', (Join-Path $sourceDir 'service')
)
$sources = @(
    (Join-Path $PSScriptRoot 'test_inputs.c'),
    (Join-Path $sourceDir 'device_driver/sht30.c'),
    (Join-Path $sourceDir 'device_driver/i2c_bus.c'),
    (Join-Path $sourceDir 'device_driver/vcnl4200.c'),
    (Join-Path $sourceDir 'service/home_inputs.c')
)
$objects = @()
foreach ($source in $sources) {
    $objectFile = Join-Path $buildDir (([IO.Path]::GetFileNameWithoutExtension($source)) + '.obj')
    & $compiler '-std=c99' '-ffreestanding' '-fno-stack-protector' '-Wall' '-Wextra' '-Werror' '-O1' @includes '-c' $source '-o' $objectFile
    if ($LASTEXITCODE -ne 0) { throw "Compile failed: $source" }
    $objects += $objectFile
}
$executable = Join-Path $buildDir 'test_inputs.exe'
# The harness has no CRT calls: returning its first failed line is the exit code.
& $linker '-flavor' 'link' '/entry:main' '/subsystem:console' '/nodefaultlib' "/out:$executable" @objects
if ($LASTEXITCODE -ne 0) { throw 'Input test link failed' }
& $executable
if ($LASTEXITCODE -ne 0) { throw "Input test failed at test_inputs.c line $LASTEXITCODE" }
Write-Output 'PASS: input lifecycle, CRC/range/error, debounce/staleness, bus sharing, timeout drain and tick wrap tests'
