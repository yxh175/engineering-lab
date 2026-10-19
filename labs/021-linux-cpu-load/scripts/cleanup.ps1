$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'cleanup_evidence.py')
if ($LASTEXITCODE -ne 0) { throw 'scoped cleanup failed' }
