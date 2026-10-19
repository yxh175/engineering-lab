$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'setup.py')
if ($LASTEXITCODE -ne 0) { throw 'owned cluster setup failed; keep evidence' }
