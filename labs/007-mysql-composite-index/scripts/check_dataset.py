"""Read-only structural check after the formal matrix; never replaces its output."""
import json
import re
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parents[1]
sys.path.insert(0, str(ROOT / "shared/scripts"))
from evidence import Evidence

SQL = """SELECT COUNT(*),COUNT(DISTINCT tenant_id,kind,seq_no),
SUM(id <> seq_no*40+kind*4+tenant_id),
SUM(tenant_id NOT BETWEEN 1 AND 4 OR kind>9 OR seq_no>4999)
FROM events;
SELECT COUNT(*) FROM events WHERE tenant_id=2 AND
((kind=3 AND seq_no>=1234) OR (kind>3 AND kind<7));
"""


def main():
    e = Evidence(LAB, "dataset-check", [Path(__file__), LAB / "sql/init.sql"],
                 {"phase": "after formal matrix, final schema", "read_only": True})
    compose = ["docker", "compose", "-p", "engineering-lab-007", "-f", str(LAB / "docker-compose.yml")]
    cid = e.require("container-id", compose + ["ps", "-q", "mysql"]).decode().strip()
    assert re.fullmatch(r"[a-f0-9]{64}", cid)
    raw = e.require("dataset-check", ["docker", "exec", "-i", "-e", "MYSQL_PWD=lab-only-password", cid,
                                     "mysql", "-uroot", "--protocol=TCP", "-h127.0.0.1", "--batch", "--raw", "--skip-column-names", "engine_lab_007"], stdin=SQL.encode())
    (e.dest / "dataset-check/input.sql").write_bytes(SQL.encode())
    rows = raw.decode().splitlines()
    passed = rows == ["200000\t200000\t0\t0", "18766"]
    e.data["trials"].append({"case": "full-cartesian-and-boundary", "passed": passed, "output_rows": rows,
                             "boundary_expected_from_integer_formula": (5000 - 1234) + 3 * 5000})
    print("Full Cartesian / primary-key formula / tuple-boundary:", "PASS" if passed else "FAIL")
    return 0 if e.seal(None if passed else "dataset check mismatch") else 1


if __name__ == "__main__":
    raise SystemExit(main())
