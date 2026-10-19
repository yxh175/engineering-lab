$ErrorActionPreference='Stop'
python (Join-Path $PSScriptRoot 'run.py')
if ($LASTEXITCODE -ne 0) { throw 'Inspect sealed failed run' }
