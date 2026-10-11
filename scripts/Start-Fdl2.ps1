param(
    [Parameter(Mandatory=$true)][string]$ToolDirectory,
    [string]$Python = 'python',
    [switch]$Reconnect
)
$ErrorActionPreference = 'Stop'
$f50Tools = (Resolve-Path -LiteralPath $ToolDirectory).Path
$f50Exe = Join-Path $f50Tools 'spd_dump.exe'
$f50Dll = Join-Path $f50Tools 'libusb-1.0.dll'
if (!(Test-Path -LiteralPath $f50Exe) -or !(Test-Path -LiteralPath $f50Dll)) {
    throw 'Use spd_dump_LibUSB_Release, with spd_dump.exe and libusb-1.0.dll together.'
}
if ($Reconnect) {
    Write-Host 'Reconnect an existing FDL2 session only once. No power cycle or mode probe here.'
    & $f50Exe --wait 30 --stage 99 --verbose 0
} else {
    & $Python (Join-Path $PSScriptRoot 'f50.py') connect --dll $f50Dll --wait 300
    if ($LASTEXITCODE -ne 0) { throw 'Mode handoff failed; no FDL loading attempted.' }
    & $f50Exe --wait 30 --verbose 0
}
Write-Host 'This wrapper performs no partition writes, erases, or automatic reboot.'

