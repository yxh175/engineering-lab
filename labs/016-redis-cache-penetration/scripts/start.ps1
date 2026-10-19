$ErrorActionPreference = 'Stop'
& docker compose -p engineering-lab-016 -f (Join-Path (Split-Path $PSScriptRoot -Parent) 'docker-compose_v2.yml') up -d --wait --wait-timeout 180
if ($LASTEXITCODE -ne 0) { throw 'MySQL startup failed' }
