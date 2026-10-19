#!/bin/sh
set -eu
lab_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
docker compose -p engineering-lab-005 -f "$lab_root/docker-compose.yml" down --remove-orphans
rm -rf -- "$lab_root/.work"
