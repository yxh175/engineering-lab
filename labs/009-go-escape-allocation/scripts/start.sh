#!/bin/sh
set -eu
lab=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$lab/.work/linux"
docker compose -p engineering-lab-009 -f "$lab/docker-compose.yml" up -d --wait
