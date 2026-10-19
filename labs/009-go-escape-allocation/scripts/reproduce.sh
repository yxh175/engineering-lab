#!/bin/sh
set -eu
lab=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python3 "$lab/scripts/run.py"
