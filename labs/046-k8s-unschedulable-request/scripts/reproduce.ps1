$ErrorActionPreference = 'Stop'
python "$PSScriptRoot/run.py"
if ($LASTEXITCODE -ne 0) { throw '046 failed; keep sealed evidence' }
