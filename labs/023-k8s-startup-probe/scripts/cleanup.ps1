$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'cleanup_evidence.py')
if ($LASTEXITCODE -ne 0) { throw 'owned cluster cleanup failed' }
