$ErrorActionPreference = 'Stop'
python "$PSScriptRoot/run.py"
if ($LASTEXITCODE -ne 0) { throw '050 failed; retain sealed evidence' }
