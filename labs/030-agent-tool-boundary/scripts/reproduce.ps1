$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'run.py')
if ($LASTEXITCODE -ne 0) { throw 'See the new results directory; keep failed evidence' }
