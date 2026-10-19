$ErrorActionPreference = 'Stop'
python "$PSScriptRoot/run_v2.py"
if ($LASTEXITCODE -ne 0) { throw '047 failed; retain evidence' }
