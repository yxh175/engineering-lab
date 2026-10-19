$ErrorActionPreference='Stop'
$taskPython=if ($env:LAB029_PYTHON) { $env:LAB029_PYTHON } else { 'python' }
& $taskPython "$PSScriptRoot/cleanup.py"
exit $LASTEXITCODE
