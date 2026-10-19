$ErrorActionPreference = 'Stop'
& docker compose -p engineering-lab-015 -f (Join-Path (Split-Path $PSScriptRoot -Parent) 'docker-compose.yml') up -d --wait --wait-timeout 180
if ($LASTEXITCODE -ne 0) { throw 'MySQL startup failed' }
