$ErrorActionPreference = 'Stop'
& docker compose -p engineering-lab-010 -f (Join-Path (Split-Path $PSScriptRoot -Parent) 'docker-compose.yml') up -d --wait
if ($LASTEXITCODE -ne 0) { throw 'Lab builder startup failed' }
