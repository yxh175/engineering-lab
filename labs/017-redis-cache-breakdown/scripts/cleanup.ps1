$ErrorActionPreference = 'Stop'
& docker compose -p engineering-lab-017 -f (Join-Path (Split-Path $PSScriptRoot -Parent) 'docker-compose.yml') down --volumes --remove-orphans
if ($LASTEXITCODE -ne 0) { throw 'Lab-specific MySQL cleanup failed' }
