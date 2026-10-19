$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'run.py')
if ($LASTEXITCODE -ne 0) { throw 'Experiment failed; raw evidence retained.' }
