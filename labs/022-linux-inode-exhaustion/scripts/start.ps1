$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot)
try {
    New-Item -ItemType Directory -Force -Path .work | Out-Null
    docker compose -p engineering-lab-022 -f docker-compose_v2.yml run --rm --no-deps builder
    if ($LASTEXITCODE -ne 0) { throw 'Linux vet/build failed' }
} finally { Pop-Location }
