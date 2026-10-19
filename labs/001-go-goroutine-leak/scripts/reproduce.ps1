param([ValidateSet('native','docker')][string]$Backend = 'native')
$ErrorActionPreference = 'Stop'
$labRoot = Split-Path $PSScriptRoot -Parent
$projectRoot = Split-Path (Split-Path $labRoot -Parent) -Parent
& python (Join-Path $projectRoot 'shared/scripts/run_go_matrix.py') --lab $labRoot --backend $Backend --repeats 10
if ($LASTEXITCODE -ne 0) { throw "Experiment failed, exit=$LASTEXITCODE. Raw evidence is preserved." }
