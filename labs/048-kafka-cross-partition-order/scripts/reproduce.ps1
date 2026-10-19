$ErrorActionPreference = 'Stop'
python "$PSScriptRoot/run.py"
if ($LASTEXITCODE -ne 0) { throw '048 failed; retain evidence' }
