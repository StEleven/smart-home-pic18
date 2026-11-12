param([Parameter(Mandatory)][string]$ClangDirectory)
$ErrorActionPreference='Stop'
$sourceDir = $env:SMARTHOME_FIRMWARE_SOURCE
if (-not $sourceDir) { throw 'Use the test.ps1 entry point.' }
$buildDir=Join-Path $PSScriptRoot '.build'
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
$objectFile=Join-Path $buildDir 'test_servo.obj'
$executable=Join-Path $buildDir 'test_servo.exe'
& (Join-Path $ClangDirectory 'clang.exe') '-std=c99' '-ffreestanding' '-fno-stack-protector' '-Wall' '-Wextra' '-Werror' '-O1' '-I' $sourceDir '-c' (Join-Path $PSScriptRoot 'test_servo.c') '-o' $objectFile
if($LASTEXITCODE -ne 0){throw 'Servo test compilation failed'}
& (Join-Path $ClangDirectory 'lld.exe') '-flavor' 'link' '/entry:main' '/subsystem:console' '/nodefaultlib' "/out:$executable" $objectFile
if($LASTEXITCODE -ne 0){throw 'Servo test link failed'}
& $executable
if($LASTEXITCODE -ne 0){throw "Servo test failed at test_servo.c line $LASTEXITCODE"}
Write-Output 'PASS: four channels, event capacity, pulse/frame timing, equal-edge merge, atomic snapshot and large-step movement'
