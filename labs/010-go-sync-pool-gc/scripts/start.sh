#!/bin/sh
set -eu
lab=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$lab/.work/linux"
docker compose -p engineering-lab-010 -f "$lab/docker-compose.yml" up -d --wait
