$ErrorActionPreference='Stop'
$taskPython=if ($env:LAB028_PYTHON) { $env:LAB028_PYTHON } else { 'python' }
& $taskPython "$PSScriptRoot/run-v2.py"
exit $LASTEXITCODE
