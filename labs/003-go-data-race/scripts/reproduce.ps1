$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'run.py')
if ($LASTEXITCODE -ne 0) { throw 'Experiment verification failed; raw evidence retained.' }
