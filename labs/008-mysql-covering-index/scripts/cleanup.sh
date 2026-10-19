#!/bin/sh
set -eu
lab_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
docker compose -p engineering-lab-008 -f "$lab_root/docker-compose.yml" down --volumes --remove-orphans
