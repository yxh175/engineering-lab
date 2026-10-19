#!/bin/sh
set -eu
lab_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
project_root=$(CDPATH= cd -- "$lab_root/../.." && pwd)
python3 "$project_root/shared/scripts/run_go_matrix.py" --lab "$lab_root" --backend "${1:-native}" --repeats 10
