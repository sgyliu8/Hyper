param([string]$DataFile)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Create the project .venv first; see README.' }
if ($DataFile) { & $python -X utf8 -m hyperlab app $DataFile }
else { & $python -X utf8 -m hyperlab app }
exit $LASTEXITCODE
