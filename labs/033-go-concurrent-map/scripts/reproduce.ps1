$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'run.py')
if ($LASTEXITCODE -ne 0) { throw 'Keep and inspect the sealed failed evidence' }
