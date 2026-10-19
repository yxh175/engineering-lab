$ErrorActionPreference = 'Stop'
& docker compose -p engineering-lab-019 -f (Join-Path $PSScriptRoot '../docker-compose.yml') down --volumes --remove-orphans
if ($LASTEXITCODE -ne 0) { throw 'Cleanup failed' }
