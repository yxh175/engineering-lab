$ErrorActionPreference = 'Stop'
& docker compose -p engineering-lab-009 -f (Join-Path (Split-Path $PSScriptRoot -Parent) 'docker-compose.yml') down --remove-orphans
if ($LASTEXITCODE -ne 0) { throw 'Lab cleanup failed' }
$labRoot=(Resolve-Path -LiteralPath (Split-Path $PSScriptRoot -Parent)).Path
$target=[System.IO.Path]::GetFullPath((Join-Path $labRoot '.work'))
if ($target -ne (Join-Path $labRoot '.work') -or -not $target.StartsWith($labRoot+[System.IO.Path]::DirectorySeparatorChar)) { throw 'Unsafe work target' }
if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
