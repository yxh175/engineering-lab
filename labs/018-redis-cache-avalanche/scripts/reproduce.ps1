$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'run.py')
if ($LASTEXITCODE -ne 0) { throw 'Experiment failed; inspect the new results directory' }
