[CmdletBinding()]
param([string]$OutputDirectory, [switch]$IncludeRuntimeArtifacts)

# Thin source-checkout wrapper; the installed package owns inventory logic.
$ErrorActionPreference = 'Stop'
$projectPython = Join-Path (Split-Path $PSScriptRoot -Parent) '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Install the project environment first; see docs/user/INSTALL.md.' }
$resourceScript = & $projectPython -c "from importlib.resources import files; print(files('hyperlab.resources').joinpath('Probe-Devices.ps1'))"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if (-not $OutputDirectory) {
    $OutputDirectory = & $projectPython -c "from hyperlab.__main__ import run_directory; print(run_directory('diagnostics'))"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $resourceScript -OutputDirectory $OutputDirectory -IncludeRuntimeArtifacts:$IncludeRuntimeArtifacts
