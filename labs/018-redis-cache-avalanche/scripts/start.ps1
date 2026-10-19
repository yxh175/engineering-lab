$ErrorActionPreference = 'Stop'
& docker compose -p engineering-lab-018 -f (Join-Path $PSScriptRoot '../docker-compose.yml') up -d --build --wait
if ($LASTEXITCODE -ne 0) { throw 'Startup failed' }
