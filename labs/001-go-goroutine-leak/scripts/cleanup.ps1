$ErrorActionPreference = 'Stop'
$labRoot = (Resolve-Path -LiteralPath (Split-Path $PSScriptRoot -Parent)).Path
& docker compose -p engineering-lab-001 -f (Join-Path $labRoot 'docker-compose.yml') down --remove-orphans
if ($LASTEXITCODE -ne 0) { throw 'Compose cleanup failed' }
$workPath = [System.IO.Path]::GetFullPath((Join-Path $labRoot '.work'))
if ($workPath -ne ($labRoot.TrimEnd('\') + '\.work')) { throw 'Unexpected cleanup target' }
if (Test-Path -LiteralPath $workPath) { Remove-Item -LiteralPath $workPath -Recurse -Force }
