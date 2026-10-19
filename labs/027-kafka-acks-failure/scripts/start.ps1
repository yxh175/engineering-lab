$ErrorActionPreference='Stop'
$taskPython=if ($env:LAB027_PYTHON) { $env:LAB027_PYTHON } else { 'python' }
& $taskPython "$PSScriptRoot/setup.py"
exit $LASTEXITCODE
