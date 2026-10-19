$ErrorActionPreference = 'Stop'
docker compose -p engineering-lab-040 -f (Join-Path $PSScriptRoot '../docker-compose_v2.yml') down -v --remove-orphans
if ($LASTEXITCODE -ne 0) { throw 'Own project cleanup failed' }
