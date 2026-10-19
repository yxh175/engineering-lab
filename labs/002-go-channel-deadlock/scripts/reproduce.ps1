param([ValidateSet('native','docker')][string]$Backend = 'native')
$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'run.py') --backend $Backend
if ($LASTEXITCODE -ne 0) { throw 'Experiment verification failed; all raw outputs retained.' }
