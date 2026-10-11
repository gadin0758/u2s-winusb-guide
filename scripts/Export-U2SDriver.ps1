param(
    [Parameter(Mandatory=$true)][ValidatePattern('^oem[0-9]+\.inf$')][string]$PublishedName,
    [Parameter(Mandatory=$true)][string]$OutDirectory
)
$ErrorActionPreference = 'Stop'
$f50Inf = Join-Path $env:windir ('INF\' + $PublishedName)
if (!(Test-Path -LiteralPath $f50Inf)) { throw 'Published INF does not exist.' }
if (!(Select-String -LiteralPath $f50Inf -Pattern 'sprdvcom' -Quiet)) {
    throw 'This INF does not identify sprdvcom; refuse to export it as the U2S driver.'
}
$f50Out = [IO.Path]::GetFullPath($OutDirectory)
New-Item -ItemType Directory -Path $f50Out -Force | Out-Null
& pnputil.exe /export-driver $PublishedName $f50Out
if ($LASTEXITCODE -ne 0) { throw 'Driver export failed.' }
Write-Host 'Exported locally. Do not commit driver binaries or private device logs.'

