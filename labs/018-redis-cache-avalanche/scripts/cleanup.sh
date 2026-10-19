#!/bin/sh
set -eu
docker compose -p engineering-lab-018 -f "$(dirname "$0")/../docker-compose.yml" down --volumes --remove-orphans
