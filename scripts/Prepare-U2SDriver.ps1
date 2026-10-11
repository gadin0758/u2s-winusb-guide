param([Parameter(Mandatory=$true)][string]$DriverInf)
$ErrorActionPreference = 'Stop'
$f50Inf = (Resolve-Path -LiteralPath $DriverInf).Path
if ([IO.Path]::GetFileName($f50Inf) -ne 'sprdvcom.inf') { throw 'Select the original signed sprdvcom.inf.' }
if (!(Select-String -LiteralPath $f50Inf -Pattern 'PID_4D00' -Quiet)) {
    throw 'Driver INF does not list the target PID_4D00.'
}
& pnputil.exe /add-driver $f50Inf /install
if ($LASTEXITCODE -ne 0) { throw 'Driver staging failed; try an administrator PowerShell.' }
Write-Host 'Driver staged. Windows ranking may retain WinUSB; installation success is not binding success.'
Write-Host 'Follow docs/restore-u2s.md: update this exact F50 device, choose Have Disk, then verify sprdvcom.'
Write-Host 'No driver packages deleted; no cameras, RNDIS adapters or registry options modified.'

