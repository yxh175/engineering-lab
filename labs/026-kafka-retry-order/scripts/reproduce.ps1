$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path "$PSScriptRoot/../../..").Path
& "$taskRoot/.work/kafka-venv/Scripts/python.exe" "$PSScriptRoot/run.py"
exit $LASTEXITCODE
