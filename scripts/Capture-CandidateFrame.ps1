param([string]$CtiPath, [string]$OutputDirectory, [string]$PixelFormat,
      [Nullable[double]]$ExposureUs, [Nullable[double]]$Gain)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$targets = @(Get-PnpDevice -PresentOnly | Where-Object InstanceId -like 'USB\VID_164C&PID_5533&MI_00\*')
if ($targets.Count -ne 1) { throw 'Exactly one investigated USB3 Vision interface must be present.' }
$captureArgs = @('-X','utf8','-m','hyperlab','acquire','--device',$targets[0].InstanceId,'--single-frame')
if ($CtiPath) { $captureArgs += @('--cti',$CtiPath) }
if ($OutputDirectory) { $captureArgs += @('--output',$OutputDirectory) }
if ($PixelFormat) { $captureArgs += @('--pixel-format',$PixelFormat) }
if ($null -ne $ExposureUs) { $captureArgs += @('--exposure-us',$ExposureUs.ToString([cultureinfo]::InvariantCulture)) }
if ($null -ne $Gain) { $captureArgs += @('--gain',$Gain.ToString([cultureinfo]::InvariantCulture)) }
& $python @captureArgs
exit $LASTEXITCODE
