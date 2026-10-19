$ErrorActionPreference = 'Stop'
python "$PSScriptRoot/run.py"
if ($LASTEXITCODE -ne 0) { throw '045 experiment failed; retain sealed evidence' }
