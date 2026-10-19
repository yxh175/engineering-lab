$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path "$PSScriptRoot/../../..").Path
& "$taskRoot/.work/kafka-venv/Scripts/python.exe" "$PSScriptRoot/run-v3.py"
exit $LASTEXITCODE
