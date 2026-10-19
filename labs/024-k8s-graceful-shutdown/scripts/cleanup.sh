#!/usr/bin/env sh
set -eu
exec python3 "$(dirname "$0")/cleanup_evidence.py"
