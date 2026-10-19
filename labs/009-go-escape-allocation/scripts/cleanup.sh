#!/bin/sh
set -eu
lab=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
docker compose -p engineering-lab-009 -f "$lab/docker-compose.yml" down --remove-orphans
case "$lab" in */labs/009-go-escape-allocation) rm -rf -- "$lab/.work" ;; *) exit 2 ;; esac
