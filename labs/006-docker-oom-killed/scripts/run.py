import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parents[1]
sys.path.insert(0, str(ROOT / "shared/scripts"))
from evidence import Evidence

CASES = ["bad-retain", "good-reuse", "manual-kill"]
IMAGE = "golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb"
LIMIT = 64 * 1024 * 1024


def verify(case, inspection, wait_out, logs, stderr, events_out):
    rows = [json.loads(s) for s in logs.decode("utf-8").splitlines() if s]
    assert rows and rows[0]["event"] == "baseline" and not stderr
    assert all(r["case"] == case and r["go_version"] == "go1.25.4" and r["pid"] == 1 for r in rows)
    assert all(r["cgroup"]["memory.max"] == LIMIT and r["cgroup"]["memory.swap.max"] == 0 for r in rows)
    assert all(r["gogc"] == "100" and r["gomemlimit"] == "off" for r in rows)
    assert inspection["HostConfig"]["Memory"] == inspection["HostConfig"]["MemorySwap"] == LIMIT
    assert inspection["Config"]["Entrypoint"] == ["/lab/.work/lab006-linux"]
    state = inspection["State"]
    exit_code = int(wait_out.strip())
    assert exit_code == state["ExitCode"] and not state["Running"] and state["Status"] == "exited"
    events = [json.loads(s) for s in events_out.decode("utf-8").splitlines() if s]
    assert events and all(e["Actor"]["ID"] == inspection["Id"] for e in events)
    actions = [e["Action"] for e in events]
    oom_events = sum(a == "oom" for a in actions)
    die = [e for e in events if e["Action"] == "die"]
    assert len(die) == 1 and int(die[0]["Actor"]["Attributes"]["exitCode"]) == exit_code
    samples = [r for r in rows if r["event"] == "sample"]
    completed = [r for r in rows if r["event"] == "completed"]
    if case == "bad-retain":
        assert state["OOMKilled"] and oom_events >= 1 and exit_code == 137 and not completed
        assert 1 <= len(samples) < 32
        assert [r["iteration"] for r in samples] == list(range(1, len(samples) + 1))
        assert all(r["retained_buffers"] == r["iteration"] for r in samples)
    elif case == "good-reuse":
        assert not state["OOMKilled"] and oom_events == 0 and exit_code == 0
        assert len(samples) == 32 and len(completed) == 1 and rows[-1]["event"] == "completed"
        assert [r["iteration"] for r in samples] == list(range(1, 33))
        assert all(r["retained_buffers"] == 1 for r in samples)
        assert completed[0]["regions_processed_bytes"] == 256 * 1024 * 1024
        assert completed[0]["page_writes"] == 32 * (8 * 1024 * 1024 // completed[0]["page_bytes"])
        assert max(r["cgroup"]["memory.current"] for r in rows) < LIMIT
    else:
        assert not state["OOMKilled"] and oom_events == 0 and exit_code == 137
        assert [r["event"] for r in rows] == ["baseline", "ready"]
        kills = [e for e in events if e["Action"] == "kill"]
        assert any(e["Actor"]["Attributes"].get("signal") == "9" for e in kills)
    last = rows[-1]
    return {"container_exit": exit_code, "oom_killed": state["OOMKilled"], "oom_events": oom_events,
            "last_iteration": last["iteration"], "completed": bool(completed),
            "last_cgroup_current": last["cgroup"]["memory.current"], "last_cgroup_peak": last["cgroup"]["memory.peak"],
            "last_heap_alloc": last["heap_alloc_bytes"], "last_rss_kib": last["process_vm_rss_kib"], "page_bytes": last["page_bytes"]}


def main():
    sources = sorted((LAB / "src").glob("*.go")) + [LAB / "go.mod", LAB / "docker-compose.yml", Path(__file__)]
    e = Evidence(LAB, "docker", sources, {"cases": CASES, "repeats_per_case": 10, "memory_bytes": LIMIT, "swap_bytes": 0, "chunk_bytes": 8 * 1024 * 1024, "iterations": 32})
    (LAB / ".work").mkdir(exist_ok=True)
    compose = ["docker", "compose", "-p", "engineering-lab-006", "-f", str(LAB / "docker-compose.yml")]
    failure, active = None, []
    try:
        e.require("docker-version", ["docker", "version"])
        info = json.loads(e.require("docker-info", ["docker", "info", "--format", "{{json .}} "]))
        assert str(info["CgroupVersion"]) == "2" and info["MemoryLimit"] and info["SwapLimit"]
        e.require("compose-version", ["docker", "compose", "version"])
        e.require("image-inspect", ["docker", "image", "inspect", IMAGE])
        e.require("go-version", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "builder", "version"])
        e.require("build", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "builder", "build", "-trimpath", "-o", ".work/lab006-linux", "./src"], timeout=180)
        e.require("go-vet", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "builder", "vet", "./src"], timeout=180)
        for case in CASES:
            for trial in range(1, 11):
                label = f"{case}-{trial:02d}"
                name = f"lab006-{e.data['run_id'].lower()}-{label}"
                active.append(name)
                e.require(label + "-start", compose + ["run", "-d", "--no-deps", "--name", name, "runner", "-case", case], timeout=30)
                if case == "manual-kill":
                    ready = False
                    for attempt in range(1, 21):
                        out = e.require(f"{label}-ready-{attempt:02d}", ["docker", "logs", name])
                        ready = any(json.loads(s)["event"] == "ready" for s in out.decode().splitlines() if s)
                        if ready:
                            break
                        time.sleep(0.1)
                    if not ready:
                        raise RuntimeError("manual-kill container did not become ready")
                    e.require(label + "-kill", ["docker", "kill", "--signal", "KILL", name])
                wait_out = e.require(label + "-wait", ["docker", "wait", name], timeout=20, container=name)
                inspection = json.loads(e.require(label + "-inspect", ["docker", "inspect", name]))[0]
                record, logs, stderr = e.run(label + "-logs", ["docker", "logs", name])
                assert record["exit_code"] == 0
                since = inspection["Created"]
                until = str(int(time.time()) + 1)
                event_out = e.require(label + "-events", ["docker", "events", "--since", since, "--until", until, "--filter", f"container={inspection['Id']}", "--format", "{{json .}}"], timeout=10)
                passed, details, error = False, {}, ""
                try:
                    details = verify(case, inspection, wait_out, logs, stderr, event_out)
                    passed = True
                except (AssertionError, KeyError, ValueError) as exc:
                    error = str(exc) or type(exc).__name__
                e.data["trials"].append({"case": case, "trial": trial, "passed": passed, "verification_error": error, **details})
                e.require(label + "-remove", ["docker", "rm", name])
                active.remove(name)
                print(f"{label}: {'PASS' if passed else 'FAIL'} exit={details.get('container_exit')} OOMKilled={details.get('oom_killed')} {error}", flush=True)
    except Exception as exc:
        failure = str(exc) or type(exc).__name__
        print(failure, file=sys.stderr)
    finally:
        for index, name in enumerate(active):
            e.run(f"failure-cleanup-{index:02d}", ["docker", "rm", "-f", name])
    if len(e.data["trials"]) != 30:
        failure = failure or "incomplete matrix"
    fields = ["case", "trial", "passed", "container_exit", "oom_killed", "oom_events", "last_iteration", "completed", "last_cgroup_current", "last_cgroup_peak", "last_heap_alloc", "last_rss_kib", "page_bytes"]
    with (e.dest / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k: t.get(k, "") for k in fields} for t in e.data["trials"])
    return 0 if e.seal(failure) else 1


if __name__ == "__main__":
    raise SystemExit(main())
