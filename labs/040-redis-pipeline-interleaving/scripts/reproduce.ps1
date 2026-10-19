$ErrorActionPreference='Stop'
python (Join-Path $PSScriptRoot 'run_v2.py')
if ($LASTEXITCODE -ne 0) { throw 'Inspect sealed failed run' }
