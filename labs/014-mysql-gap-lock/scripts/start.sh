#!/bin/sh
set -eu
lab_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
docker compose -p engineering-lab-014 -f "$lab_root/docker-compose.yml" up -d --wait --wait-timeout 180
