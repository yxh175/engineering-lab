#!/bin/sh
set -eu
lab=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
docker compose -p engineering-lab-011 -f "$lab/docker-compose.yml" down --remove-orphans
case "$lab" in */labs/010-go-sync-pool-gc) rm -rf -- "$lab/.work" ;; *) exit 2 ;; esac
