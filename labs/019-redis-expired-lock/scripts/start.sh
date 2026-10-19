#!/bin/sh
set -eu
docker compose -p engineering-lab-019 -f "$(dirname "$0")/../docker-compose.yml" up -d --build --wait
