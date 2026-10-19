$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'run_v3.py')
if ($LASTEXITCODE -ne 0) { throw 'Inspect sealed failed run; preserve raw evidence' }
