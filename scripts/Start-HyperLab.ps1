param([string]$DataFile, [switch]$Legacy, [string]$BenchmarkLog)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Create the project .venv first; see README.' }
$launchArgs = @('-X','utf8','-m','hyperlab','app')
if ($DataFile) { $launchArgs += $DataFile }
if ($Legacy) { $launchArgs += '--legacy' }
if ($BenchmarkLog) { $launchArgs += @('--benchmark-log',$BenchmarkLog) }
& $python @launchArgs
exit $LASTEXITCODE
