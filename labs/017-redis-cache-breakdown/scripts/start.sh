#!/bin/sh
set -eu
lab_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
docker compose -p engineering-lab-017 -f "$lab_root/docker-compose.yml" up --build -d --wait --wait-timeout 180
