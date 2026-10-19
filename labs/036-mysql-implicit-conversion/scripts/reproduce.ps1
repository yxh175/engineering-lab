$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'run.py')
if ($LASTEXITCODE -ne 0) { throw 'Keep the failed sealed run and inspect it' }
