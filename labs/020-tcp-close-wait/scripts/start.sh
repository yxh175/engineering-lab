#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p .work
docker compose -p engineering-lab-020 build builder
docker compose -p engineering-lab-020 run --rm --no-deps builder
