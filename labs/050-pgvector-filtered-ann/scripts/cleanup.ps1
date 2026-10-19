$ErrorActionPreference = 'Stop'
docker compose -p engineering-lab-050 -f "$PSScriptRoot/../docker-compose.yml" down -v --remove-orphans
if ($LASTEXITCODE -ne 0) { throw 'Owned compose cleanup failed' }
