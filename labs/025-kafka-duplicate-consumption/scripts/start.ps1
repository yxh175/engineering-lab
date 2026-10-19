$ErrorActionPreference='Stop'
$taskPython=if ($env:LAB025_PYTHON) { $env:LAB025_PYTHON } else { 'python' }
& $taskPython "$PSScriptRoot/bootstrap.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $taskPython "$PSScriptRoot/setup.py"
exit $LASTEXITCODE
