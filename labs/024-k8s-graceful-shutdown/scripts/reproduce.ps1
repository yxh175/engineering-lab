$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'run.py')
if ($LASTEXITCODE -ne 0) { throw 'experiment failed; keep raw evidence' }
