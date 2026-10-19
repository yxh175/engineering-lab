import csv
import json
import re
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parents[1]
sys.path.insert(0, str(ROOT / "shared/scripts"))
from evidence import Evidence

IMAGE = "mysql:8.4@sha256:0744ee5ef89ce6ccfa13de3e579fe6b9e27f93dd70da9c06d2c908b1b193fb8d"
CASES = json.loads((LAB / "src/cases.json").read_text(encoding="utf-8"))


def expected_rows(case):
    if case.startswith("prefix-"):
        return [(s * 40 + 3 * 4 + 2, 2, 3, s) for s in range(100, 110)]
    if case.startswith("range-"):
        return [(1234 * 40 + k * 4 + 2, 2, k, 1234) for k in range(3, 7)]
    return [(1234 * 40 + k * 4 + t, t, k, 1234) for k in range(10) for t in range(1, 5)]


def tree_nodes(raw):
    nodes = []
    for line in raw.decode("utf-8").splitlines():
        found = re.search(r"\(actual time=([\deE.+-]+)\.\.([\deE.+-]+) rows=([\deE.+-]+) loops=(\d+)\)", line)
        if found:
            start, end, rows, loops = found.groups()
            nodes.append({"text": line.strip(), "first_ms": float(start), "end_ms": float(end), "rows_per_loop": float(rows), "loops": int(loops)})
    assert nodes, "no actual execution nodes"
    return nodes


def verify(config, plan_raw, tree_raw, rows_raw):
    plan = json.loads(plan_raw.decode("utf-8"))
    table = plan["query_block"]["table"]
    actual = [tuple(map(int, s.split("\t"))) for s in rows_raw.decode("utf-8").splitlines() if s]
    expected = expected_rows(config["case"])
    assert len(expected) == config["expected_rows"] and sorted(actual) == sorted(expected), "result-set mismatch"
    nodes = tree_nodes(tree_raw)
    assert nodes[0]["rows_per_loop"] == len(expected) and nodes[0]["loops"] == 1
    leaf = nodes[-1]
    assert leaf["loops"] == 1 and "index" in leaf["text"].lower()
    read = leaf["rows_per_loop"]
    case = config["case"]
    if case.startswith("prefix-"):
        assert table["key"] == "idx_tenant_kind_seq" and read == 10
    elif case == "suffix-skip-off":
        assert read == 200000, "skip-off did not scan the full covering index"
    elif case == "range-before-equality":
        assert read >= 10000, "range candidate interval was unexpectedly narrow"
    elif config["phase"] == "after":
        assert table["key"] == "idx_seq_tenant_kind" and read == len(expected)
    return {"index": table.get("key"), "access_type": table["access_type"], "used_key_parts": table.get("used_key_parts", []),
            "estimated_rows": table["rows_examined_per_scan"], "using_index_for_skip_scan": table.get("using_index_for_skip_scan", False),
            "leaf_actual_rows": read, "returned_rows": len(actual), "result_id_sum": sum(r[0] for r in actual),
            "root_end_ms_instrumented": nodes[0]["end_ms"], "nodes": nodes}


def main():
    sources = [LAB / "docker-compose.yml", LAB / "src/cases.json", LAB / "sql/init.sql", LAB / "sql/good.sql", Path(__file__)]
    e = Evidence(LAB, "docker", sources, {"mysql_expected_version": "8.4.11", "row_count": 200000, "tenants": 4, "kinds": 10, "seq_values": 5000, "repeats_per_case": 10, "cases": [c["case"] for c in CASES], "warmup_per_case": 1, "timing_is_benchmark": False})
    compose = ["docker", "compose", "-p", "engineering-lab-007", "-f", str(LAB / "docker-compose.yml")]
    failure, container = None, None

    def sql(label, text, database=True):
        argv = ["docker", "exec", "-i", "-e", "MYSQL_PWD=lab-only-password", container,
                "mysql", "-uroot", "--protocol=TCP", "-h127.0.0.1", "--batch", "--raw", "--skip-column-names"]
        if database:
            argv.append("engine_lab_007")
        record, out, err = e.run(label, argv, stdin=text.encode("utf-8"), timeout=180)
        (e.dest / label / "input.sql").write_bytes(text.encode("utf-8"))
        if record["exit_code"] != 0:
            raise RuntimeError(f"{label} MySQL exit {record['exit_code']}")
        return out

    try:
        e.require("docker-version", ["docker", "version"])
        e.require("compose-version", ["docker", "compose", "version"])
        e.require("image-inspect", ["docker", "image", "inspect", IMAGE])
        e.require("startup", compose + ["up", "-d", "--wait", "--wait-timeout", "180"], timeout=210)
        container = e.require("container-id", compose + ["ps", "-q", "mysql"]).decode().strip()
        assert re.fullmatch(r"[a-f0-9]{64}", container)
        e.require("container-inspect-before", ["docker", "inspect", container])
        metadata = sql("server-metadata", "SELECT VERSION(),@@version_comment,@@innodb_buffer_pool_size,@@innodb_stats_persistent_sample_pages,@@optimizer_switch,@@transaction_isolation;\n", database=False)
        assert metadata.decode().startswith("8.4.11\t")
        sql("initialize-data", (LAB / "sql/init.sql").read_text(encoding="utf-8"), database=False)
        distribution = sql("dataset-audit", "SELECT COUNT(*),MIN(id),MAX(id),COUNT(DISTINCT tenant_id),COUNT(DISTINCT kind),COUNT(DISTINCT seq_no) FROM events;\nSHOW CREATE TABLE events;\n")
        assert distribution.decode().splitlines()[0] == "200000\t1\t200000\t4\t10\t5000"
        for phase in ["before", "after"]:
            if phase == "after":
                sql("add-good-index", (LAB / "sql/good.sql").read_text(encoding="utf-8"))
            for config in [c for c in CASES if c["phase"] == phase]:
                case = config["case"]
                query = "SELECT id,tenant_id,kind,seq_no FROM events WHERE " + config["where"]
                setup = "SET SESSION optimizer_switch='" + config["switch"] + "';\n"
                sql(case + "-warmup", setup + "EXPLAIN ANALYZE FORMAT=TREE " + query + ";\n")
                for trial in range(1, 11):
                    label = f"{case}-{trial:02d}"
                    plan = sql(label + "-plan", setup + "EXPLAIN FORMAT=JSON " + query + ";\n")
                    tree = sql(label + "-analyze", setup + "EXPLAIN ANALYZE FORMAT=TREE " + query + ";\n")
                    result = sql(label + "-rows", setup + query + ";\n")
                    passed, details, error = False, {}, ""
                    try:
                        details = verify(config, plan, tree, result)
                        passed = True
                    except (AssertionError, KeyError, ValueError) as exc:
                        error = str(exc) or type(exc).__name__
                    e.data["trials"].append({"case": case, "phase": phase, "trial": trial, "passed": passed, "verification_error": error, **details})
                    print(f"{label}: {'PASS' if passed else 'FAIL'} leaf={details.get('leaf_actual_rows')} returned={details.get('returned_rows')} index={details.get('index')} {error}", flush=True)
        # Optimizer traces are collected after formal repetitions on the final schema.
        for name, where, index in [("range-original", "tenant_id=2 AND kind>=3 AND kind<7 AND seq_no=1234", "idx_tenant_kind_seq"),
                                   ("range-fixed", "tenant_id=2 AND kind>=3 AND kind<7 AND seq_no=1234", "idx_seq_tenant_kind")]:
            sql(name + "-optimizer-trace", "SET optimizer_trace='enabled=on';\nEXPLAIN SELECT id,tenant_id,kind,seq_no FROM events FORCE INDEX (" + index + ") WHERE " + where + ";\nSELECT TRACE FROM INFORMATION_SCHEMA.OPTIMIZER_TRACE;\n")
        e.require("server-logs", compose + ["logs", "--no-color", "mysql"])
        e.require("container-inspect-after", ["docker", "inspect", container])
    except Exception as exc:
        failure = str(exc) or type(exc).__name__
        print(failure, file=sys.stderr)
        if container:
            e.run("failure-server-logs", compose + ["logs", "--no-color", "mysql"])
    if len(e.data["trials"]) != 70:
        failure = failure or "incomplete matrix"
    fields = ["case", "phase", "trial", "passed", "index", "access_type", "estimated_rows", "using_index_for_skip_scan", "leaf_actual_rows", "returned_rows", "result_id_sum", "root_end_ms_instrumented"]
    with (e.dest / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k: t.get(k, "") for k in fields} for t in e.data["trials"])
    return 0 if e.seal(failure) else 1


if __name__ == "__main__":
    raise SystemExit(main())
