#!/bin/sh
set -eu
lab_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
docker compose -p engineering-lab-004 -f "$lab_root/docker-compose.yml" down --remove-orphans
case "$lab_root/.work" in */004-linux-fd-exhaustion/.work) rm -rf -- "$lab_root/.work" ;; *) exit 2 ;; esac
