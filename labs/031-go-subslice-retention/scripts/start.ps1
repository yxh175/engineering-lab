$ErrorActionPreference = 'Stop'
go version
if ($LASTEXITCODE -ne 0) { throw 'Go 1.25.4 required' }
python --version
