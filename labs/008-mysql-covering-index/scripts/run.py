import csv
import hashlib
import json
import re
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parents[1]
sys.path.insert(0, str(ROOT / "shared/scripts"))
from evidence import Evidence, sha
from mysql_cartesian import render

IMAGE = "mysql:8.4@sha256:0744ee5ef89ce6ccfa13de3e579fe6b9e27f93dd70da9c06d2c908b1b193fb8d"
CASES = json.loads((LAB / "src/cases.json").read_text())
WHERE = "tenant_id=2 AND kind=3 AND seq_no>=1000 AND seq_no<1512"
SIZE_SQL = "SELECT index_name,stat_name,stat_value,@@innodb_page_size FROM mysql.innodb_index_stats WHERE database_name='engine_lab_008' AND table_name='events' AND stat_name IN ('size','n_leaf_pages') ORDER BY index_name,stat_name;\n"


def query(config):
    return "SELECT " + config["columns"] + " FROM events WHERE " + WHERE


def verify(config, label, plan_raw, tree_raw, sample_raw):
    table = json.loads(plan_raw)["query_block"]["table"]
    nodes = []
    for line in tree_raw.decode().splitlines():
        f = re.search(r"\(actual time=([\deE.+-]+)\.\.([\deE.+-]+) rows=([\deE.+-]+) loops=(\d+)\)", line)
        if f:
            nodes.append({"text": line.strip(), "rows": float(f[3]), "loops": int(f[4])})
    assert nodes and all(n["rows"] == 512 and n["loops"] == 1 for n in nodes)
    covering = "covering index" in nodes[-1]["text"].lower()
    assert covering == config["covering"] and table.get("using_index", False) == covering
    if config["case"] == "wide-after":
        assert table["key"] == "idx_tenant_kind_seq_payload"
    else:
        assert table["key"] == "idx_tenant_kind_seq"
    lines = sample_raw.decode().splitlines()
    assert lines[0] == "BEGIN_ROWS" and "END_ROWS" in lines
    end = lines.index("END_ROWS")
    texts = lines[1:end]
    assert len(texts) == 512 and len(lines) == end + 2
    actual, expected = [], []
    wide = config["case"].startswith("wide-")
    for line in texts:
        fields = line.split("\t")
        assert len(fields) == (5 if wide else 4)
        actual.append(tuple(map(int, fields[:4])) + ((fields[4],) if wide else ()))
    for s in range(1000, 1512):
        ident = s * 40 + 3 * 4 + 2
        expected.append((ident, 2, 3, s) + ((f"event-{ident}".ljust(512, "x"),) if wide else ()))
    assert sorted(actual) == sorted(expected), "full result set mismatch"
    metrics = lines[-1].split("\t")
    assert len(metrics) == 9 and metrics[0] == "PSSTAT"
    thread, event, timer, lock, sent, examined, errno = map(int, metrics[1:8])
    target = f"/*lab008-{label}*/ " + query(config)
    assert metrics[8] == target, "Performance Schema SQL tag mismatch"
    assert timer > 0 and thread > 0 and event > 0 and sent == 512 and errno == 0
    canonical = json.dumps(sorted(actual), separators=(",", ":")).encode()
    return {"index": table["key"], "access_type": table["access_type"], "covering": covering,
            "leaf_actual_rows": nodes[-1]["rows"], "returned_rows": len(actual), "nodes": nodes,
            "result_text_bytes": sum(len((s + "\n").encode()) for s in texts),
            "result_canonical_sha256": hashlib.sha256(canonical).hexdigest(),
            "ps_thread_id": thread, "ps_event_id": event, "ps_timer_wait_ps": timer,
            "ps_lock_time_ps": lock, "ps_rows_sent": sent, "ps_rows_examined": examined,
            "statement_ms": timer / 1000000000}


def main():
    e = Evidence(LAB, "docker", [LAB / "docker-compose.yml", LAB / "src/cases.json", LAB / "sql/init.sql", LAB / "sql/good.sql", Path(__file__)],
                 {"mysql_expected_version": "8.4.11", "row_count": 200000, "payload_bytes": 512,
                  "expected_result_rows": 512, "where": WHERE, "repeats_per_case": 10, "warmup_per_case": 1,
                  "concurrency": 1, "timer": "completed ordinary SELECT P_S TIMER_WAIT picoseconds",
                  "case_order": "before: narrow/wide per round; after: wide/narrow per round", "cold_cache": False})
    e.data["shared_source_sha256"]["shared/scripts/mysql_cartesian.py"] = sha(ROOT / "shared/scripts/mysql_cartesian.py")
    compose = ["docker", "compose", "-p", "engineering-lab-008", "-f", str(LAB / "docker-compose.yml")]
    container, failure = None, None

    def sql(label, text, database=True, timeout=180):
        argv = ["docker", "exec", "-i", "-e", "MYSQL_PWD=lab-only-password", container,
                "mysql", "-uroot", "--protocol=TCP", "-h127.0.0.1", "--batch", "--raw", "--skip-column-names", "--comments"]
        if database:
            argv.append("engine_lab_008")
        record, out, err = e.run(label, argv, stdin=text.encode(), timeout=timeout)
        (e.dest / label / "input.sql").write_bytes(text.encode())
        if record["exit_code"] != 0:
            raise RuntimeError(f"{label} MySQL exit {record['exit_code']}")
        return out

    try:
        assert (LAB / "sql/init.sql").read_text() == render("engine_lab_008")
        e.require("docker-version", ["docker", "version"])
        e.require("compose-version", ["docker", "compose", "version"])
        e.require("image-inspect", ["docker", "image", "inspect", IMAGE])
        e.require("startup", compose + ["up", "-d", "--wait", "--wait-timeout", "180"], timeout=210)
        container = e.require("container-id", compose + ["ps", "-q", "mysql"]).decode().strip()
        assert re.fullmatch(r"[a-f0-9]{64}", container)
        e.require("container-inspect-before", ["docker", "inspect", container])
        metadata = sql("server-metadata", "SELECT VERSION(),@@innodb_buffer_pool_size,@@innodb_stats_persistent_sample_pages,@@optimizer_switch,@@transaction_isolation,@@performance_schema;\n", database=False)
        assert metadata.decode().startswith("8.4.11\t")
        init = sql("initialize-data", (LAB / "sql/init.sql").read_text(), database=False, timeout=240)
        assert "200000\t200000\t0\t0\t512\t512" in init.decode().splitlines()
        sql("setup-instrumentation", "UPDATE performance_schema.setup_consumers SET ENABLED='YES' WHERE NAME IN ('events_statements_current','events_statements_history');\nUPDATE performance_schema.setup_instruments SET ENABLED='YES',TIMED='YES' WHERE NAME='statement/sql/select';\nSELECT NAME,ENABLED FROM performance_schema.setup_consumers WHERE NAME LIKE '%statements%';\nSELECT NAME,ENABLED,TIMED FROM performance_schema.setup_instruments WHERE NAME='statement/sql/select';\nSELECT * FROM performance_schema.performance_timers;\n")
        for phase in ["before", "after"]:
            if phase == "after":
                sql("add-covering-index", (LAB / "sql/good.sql").read_text(), timeout=240)
            sql("index-size-" + phase, SIZE_SQL)
            cases = [c for c in CASES if c["phase"] == phase]
            for config in cases:
                sql(config["case"] + "-warmup", query(config) + ";\n")
            for trial in range(1, 11):
                for config in cases:
                    label = f"{config['case']}-{trial:02d}"
                    plan = sql(label + "-plan", "EXPLAIN FORMAT=JSON " + query(config) + ";\n")
                    tree = sql(label + "-analyze", "EXPLAIN ANALYZE FORMAT=TREE " + query(config) + ";\n")
                    tag = f"/*lab008-{label}*/"
                    sample = sql(label + "-sample", "SELECT 'BEGIN_ROWS';\n" + tag + " " + query(config) + ";\nSELECT 'END_ROWS';\n"
                                 "SELECT 'PSSTAT',THREAD_ID,EVENT_ID,TIMER_WAIT,LOCK_TIME,ROWS_SENT,ROWS_EXAMINED,MYSQL_ERRNO,SQL_TEXT "
                                 "FROM performance_schema.events_statements_history WHERE THREAD_ID=(SELECT THREAD_ID FROM performance_schema.threads WHERE PROCESSLIST_ID=CONNECTION_ID()) "
                                 "AND SQL_TEXT LIKE '" + tag + "%' ORDER BY EVENT_ID DESC LIMIT 1;\n")
                    details, error, passed = {}, "", False
                    try:
                        details = verify(config, label, plan, tree, sample)
                        passed = True
                    except (AssertionError, ValueError, KeyError, IndexError) as exc:
                        error = str(exc) or type(exc).__name__
                    e.data["trials"].append({"case": config["case"], "phase": phase, "trial": trial, "passed": passed, "verification_error": error, **details})
                    print(f"{label}: {'PASS' if passed else 'FAIL'} covering={details.get('covering')} ms={details.get('statement_ms')} bytes={details.get('result_text_bytes')} {error}", flush=True)
        for family in ["narrow", "wide"]:
            ts = [t for t in e.data["trials"] if t["case"].startswith(family)]
            assert len(ts) == 20 and all(t["passed"] for t in ts)
            assert len({t["result_canonical_sha256"] for t in ts}) == 1 and len({t["result_text_bytes"] for t in ts}) == 1
        e.require("server-logs", compose + ["logs", "--no-color", "mysql"])
        e.require("container-inspect-after", ["docker", "inspect", container])
    except Exception as exc:
        failure = str(exc) or type(exc).__name__
        print(failure, file=sys.stderr)
        if container:
            e.run("failure-server-logs", compose + ["logs", "--no-color", "mysql"])
    if len(e.data["trials"]) != 40:
        failure = failure or "incomplete matrix"
    fields = ["case", "phase", "trial", "passed", "index", "covering", "leaf_actual_rows", "returned_rows", "result_text_bytes", "result_canonical_sha256", "ps_timer_wait_ps", "ps_rows_sent", "ps_rows_examined", "statement_ms"]
    with (e.dest / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k: t.get(k, "") for k in fields} for t in e.data["trials"])
    return 0 if e.seal(failure) else 1


if __name__ == "__main__":
    raise SystemExit(main())
