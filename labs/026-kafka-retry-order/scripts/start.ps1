$ErrorActionPreference='Stop'
$taskPython=if ($env:LAB026_PYTHON) { $env:LAB026_PYTHON } else { 'python' }
& $taskPython "$PSScriptRoot/setup.py"
exit $LASTEXITCODE
