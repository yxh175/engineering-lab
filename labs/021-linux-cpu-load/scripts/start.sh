#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p .work
docker compose -p engineering-lab-021 -f docker-compose_v2.yml run --rm --no-deps builder
