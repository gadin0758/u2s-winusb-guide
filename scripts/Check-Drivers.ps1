$ErrorActionPreference = 'Stop'
Write-Host 'Read-only connected-device inventory. Target download device: USB VID_1782 PID_4D00.'
$f50Devices = & pnputil.exe /enum-devices /connected /drivers
if ($LASTEXITCODE -ne 0) { throw 'PnP inventory failed.' }
$f50Devices | Select-String -Pattern 'VID_1782&PID_4D00|VID_19D2|SPRD U2S|WinUSB|sprdvcom' -Context 0,10
Write-Host 'Normal runtime USB and download-mode USB are different devices.'
Write-Host 'For the exact target instance shown above, inspect: pnputil /enum-devices /instanceid "<ID>" /drivers /properties'

