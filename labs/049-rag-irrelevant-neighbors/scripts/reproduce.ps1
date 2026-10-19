$ErrorActionPreference = 'Stop'
$repoPath = (Resolve-Path "$PSScriptRoot/../../..").Path
& "$repoPath/.work/rag-venv/Scripts/python.exe" "$PSScriptRoot/run.py"
if ($LASTEXITCODE -ne 0) { throw '049 failed; keep evidence' }
