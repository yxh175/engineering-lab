#!/bin/sh
set -eu
python3 "$(dirname "$0")/run.py" --backend "${1:-native}"
