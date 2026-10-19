$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'run_v4.py')
if ($LASTEXITCODE -ne 0) { throw 'Experiment verification failed; inspect the new results directory' }
