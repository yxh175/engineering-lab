$ErrorActionPreference = 'Stop'
& docker compose -p engineering-lab-017 -f (Join-Path (Split-Path $PSScriptRoot -Parent) 'docker-compose.yml') up --build -d --wait --wait-timeout 180
if ($LASTEXITCODE -ne 0) { throw 'MySQL startup failed' }
