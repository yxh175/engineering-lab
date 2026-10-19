$ErrorActionPreference = 'Stop'
$ownedIds = @(docker ps -aq --filter 'label=engineering-lab.lab=044')
if ($LASTEXITCODE -ne 0) { throw 'Cannot list owned containers' }
foreach ($ownedId in $ownedIds) {
    if ($ownedId -notmatch '^[a-f0-9]{12,64}$') { throw 'Unexpected container id' }
    docker rm -f $ownedId
    if ($LASTEXITCODE -ne 0) { throw 'Owned cleanup failed' }
}
