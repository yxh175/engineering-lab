$ErrorActionPreference='Stop'
$taskPython=if ($env:LAB029_PYTHON) { $env:LAB029_PYTHON } else { 'python' }
& $taskPython "$PSScriptRoot/run.py"
exit $LASTEXITCODE
