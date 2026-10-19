#!/bin/sh
set -eu
lab_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
docker compose -p engineering-lab-016 -f "$lab_root/docker-compose_v2.yml" up -d --wait --wait-timeout 180
