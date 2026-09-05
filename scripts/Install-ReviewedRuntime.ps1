param([switch]$ApproveDriverInstallation)
$ErrorActionPreference = 'Stop'
if (-not $ApproveDriverInstallation) {
    throw 'No changes made. Requires separate owner approval for Windows USB3 Vision driver installation.'
}
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'This operation needs an elevated PowerShell; no installation was attempted.'
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$package = Join-Path $projectRoot 'local\downloads\ImpactAcquire-x86_64-3.7.2.exe'
$signature = Get-AuthenticodeSignature -FilePath $package
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Balluff MV GmbH') {
    throw 'Package signature does not match the reviewed valid Balluff signer.'
}
# Locally measured fingerprint of the official signed download, not a vendor-published checksum.
$expectedHash = '0B422544B8B15961D57D88488920BD3E3995E1C24ED8E209904F915D89BB5B64'
if ((Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash -ne $expectedHash) {
    throw 'Package changed since the static review; installation refused.'
}
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$log = Join-Path $projectRoot ('local\diagnostics\install-' + $stamp + '.log')
$arguments = @('/install','/quiet','/norestart','U3V_SUPPORT=yes','GEV_SUPPORT=no',
    'GEV_NDIS_DRIVER_INSTALL=no','PCIE_SUPPORT=no','USB2_SUPPORT=no',
    'VIRTUAL_DEVICE_SUPPORT=no','LABVIEW_SUPPORT=no','/log',('"' + $log + '"'))
$process = Start-Process -FilePath $package -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
@{ package=$package; exit_code=$process.ExitCode; log=$log; reboot_performed=$false;
   approval_switch=$true; time=(Get-Date).ToUniversalTime().ToString('o') } |
    ConvertTo-Json | Set-Content -Encoding utf8 ($log + '.json')
if ($process.ExitCode -eq 3010) { Write-Warning 'Installer requested reboot; no reboot performed.' }
elseif ($process.ExitCode -ne 0) { throw "Installer failed with exit code $($process.ExitCode). See $log" }
Write-Output "Installer returned $($process.ExitCode); run the read-only probe before acquisition."
