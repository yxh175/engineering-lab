$ErrorActionPreference = 'Stop'
& kind delete cluster --name engineering-lab-046
if ($LASTEXITCODE -ne 0) { throw 'Owned cluster cleanup failed' }
