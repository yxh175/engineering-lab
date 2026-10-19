$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot)
try {
    docker compose -p engineering-lab-020 build builder
    if ($LASTEXITCODE -ne 0) { throw 'image build failed' }
    New-Item -ItemType Directory -Force -Path .work | Out-Null
    docker compose -p engineering-lab-020 run --rm --no-deps builder
    if ($LASTEXITCODE -ne 0) { throw 'Linux vet/build failed' }
} finally { Pop-Location }
