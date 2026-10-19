$ErrorActionPreference='Stop'
$taskPython=if ($env:LAB027_PYTHON) { $env:LAB027_PYTHON } else { 'python' }
& $taskPython "$PSScriptRoot/cleanup.py"
exit $LASTEXITCODE
