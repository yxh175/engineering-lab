$ErrorActionPreference = 'Stop'
docker compose -p engineering-lab-038 -f (Join-Path $PSScriptRoot '../docker-compose.yml') down -v --remove-orphans
if ($LASTEXITCODE -ne 0) { throw 'Own project cleanup failed' }
