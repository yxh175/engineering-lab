#!/bin/sh
set -eu
lab_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
docker compose -p engineering-lab-001 -f "$lab_root/docker-compose.yml" down --remove-orphans
if [ -d "$lab_root/.work" ]; then
  case "$lab_root/.work" in */001-go-goroutine-leak/.work) rm -rf -- "$lab_root/.work" ;; *) exit 2 ;; esac
fi
