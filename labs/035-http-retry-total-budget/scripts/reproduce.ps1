$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'run.py')
if ($LASTEXITCODE -ne 0) { throw 'Inspect the new sealed evidence failure' }
