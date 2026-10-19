$ErrorActionPreference = 'Stop'
python --version
if ($LASTEXITCODE -ne 0) { throw 'CPython 3.12 required' }
