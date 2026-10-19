$ErrorActionPreference='Stop'
$taskPython=if ($env:LAB025_PYTHON) { $env:LAB025_PYTHON } else { 'python' }
& $taskPython "$PSScriptRoot/cleanup.py"
exit $LASTEXITCODE
