import argparse
import csv
import json
import os
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parents[1]
sys.path.insert(0, str(ROOT / "shared/scripts"))
from evidence import Evidence

CASES = ["bad-unclosed", "close-only", "good-drain-close", "bad-limited"]
IMAGE = "golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb"
BODY_BYTES = 256 * 1024


def verify(case, code, out, err):
    events = [json.loads(s) for s in out.decode("utf-8").splitlines() if s]
    assert all(e["case"] == case for e in events)
    config, summary, idle, cleanup = events[0], events[-3], events[-2], events[-1]
    assert [e["event"] for e in [config, summary, idle, cleanup]] == ["config", "summary", "after-close-idle", "after-cleanup"]
    assert config["go_version"] == "go1.25.4" and config["requests_planned"] == 16
    assert config["body_bytes"] == BODY_BYTES and config["max_idle_per_host"] == 2
    assert config["max_conns_per_host"] == (4 if case == "bad-limited" else 0)
    good, limited, unclosed = case == "good-drain-close", case == "bad-limited", case in ["bad-unclosed", "bad-limited"]
    successes, accepted = (4 if limited else 16), (1 if good else 4 if limited else 16)
    requests = [e for e in events if e["event"] == "request"]
    failures = [e for e in events if e["event"] == "request-error"]
    assert len(requests) == successes and summary["successes"] == successes
    assert [e["request"] for e in requests] == list(range(1, successes + 1))
    assert all(e["status"] == 200 and e["protocol"] == "HTTP/1.1" and e["content_length"] == BODY_BYTES for e in requests)
    assert all(e["trace"]["got_conn_calls"] == 1 for e in requests)
    assert [e["server_connection_id"] for e in requests] == ([1] * 16 if good else list(range(1, successes + 1)))
    assert [e["trace"]["reused"] for e in requests] == ([False] + [True] * 15 if good else [False] * successes)
    assert len({e["trace"]["local"] for e in requests}) == accepted
    assert all(e["read_bytes"] == (BODY_BYTES if good else 0) and e["body_closed"] == (not unclosed) for e in requests)
    assert summary["drained_bytes"] == (16 * BODY_BYTES if good else 0)
    assert summary["body_close_calls"] == (0 if unclosed else 16)
    assert summary["held_bodies"] == (successes if unclosed else 0)
    assert summary["reused_requests"] == (15 if good else 0)
    assert summary["attempts"] == (5 if limited else 16) and summary["deadline_exceeded"] == limited
    assert summary["server"]["accepted"] == accepted and summary["server"]["requests"] == successes
    assert summary["server"]["live"] == (successes if unclosed else 1 if good else 0)
    assert summary["server"]["closed"] == (16 if case == "close-only" else 0)
    assert summary["server"]["peak_live"] == (successes if unclosed else 1)
    assert idle["server"]["live"] == (successes if unclosed else 0)
    assert cleanup["server"]["live"] == 0 and cleanup["server"]["accepted"] == cleanup["server"]["closed"] == accepted
    history = cleanup["transitions"]
    assert [s["connection_id"] for s in history if s["state"] == "new"] == list(range(1, accepted + 1))
    assert sorted(s["connection_id"] for s in history if s["state"] == "closed") == list(range(1, accepted + 1))
    assert len(cleanup["writes"]) == successes
    if good:
        assert all(w["bytes_written"] == BODY_BYTES and not w.get("error") for w in cleanup["writes"])
    if limited:
        assert code == 3 and b"context deadline exceeded" in err
        assert len(failures) == 1 and failures[0]["request"] == 5 and failures[0]["deadline_exceeded"]
        assert failures[0]["trace"]["got_conn_calls"] == 0 and failures[0]["server"]["accepted"] == 4
    else:
        assert code == 0 and not err and not failures
    return {"successes": successes, "accepted": accepted, "reused": summary["reused_requests"],
            "live_before_cleanup": summary["server"]["live"], "live_after_close_idle": idle["server"]["live"],
            "live_after_cleanup": cleanup["server"]["live"], "drained_bytes": summary["drained_bytes"], "deadline_exceeded": limited}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--backend", choices=["native", "docker"], default="native")
    args = p.parse_args()
    sources = sorted((LAB / "src").glob("*.go")) + [LAB / "go.mod", LAB / "docker-compose.yml", Path(__file__)]
    e = Evidence(LAB, args.backend, sources, {"cases": CASES, "repeats_per_case": 10, "requests_planned": 16, "body_bytes": BODY_BYTES, "limited_max_conns": 4, "limited_request_timeout_ms": 250})
    (LAB / ".work").mkdir(exist_ok=True)
    compose = ["docker", "compose", "-p", "engineering-lab-005", "-f", str(LAB / "docker-compose.yml")]
    binary = LAB / ".work" / ("lab005-native.exe" if os.name == "nt" else "lab005-native")
    failure = None
    try:
        if args.backend == "native":
            e.require("go-version", ["go", "version"])
            e.require("go-env", ["go", "env", "GOOS", "GOARCH", "CGO_ENABLED"])
            e.require("build", ["go", "build", "-trimpath", "-o", str(binary), "./src"], timeout=180)
            e.require("go-vet", ["go", "vet", "./src"], timeout=180)
        else:
            e.require("docker-version", ["docker", "version"])
            e.require("compose-version", ["docker", "compose", "version"])
            e.require("image-inspect", ["docker", "image", "inspect", IMAGE])
            e.require("go-version", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "version"])
            e.require("go-env", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "env", "GOOS", "GOARCH", "CGO_ENABLED"])
            e.require("build", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "build", "-trimpath", "-o", ".work/lab005-linux", "./src"], timeout=180)
            e.require("go-vet", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "vet", "./src"], timeout=180)
        for case in CASES:
            for trial in range(1, 11):
                label = f"{case}-{trial:02d}"
                container = None
                argv = [str(binary), "-case", case]
                if args.backend == "docker":
                    container = f"lab005-{e.data['run_id'].lower()}-{label}"
                    argv = compose + ["run", "--rm", "--no-deps", "--name", container, "runner", "-case", case]
                record, out, err = e.run(label, argv, timeout=20, container=container)
                passed, details, error = False, {}, ""
                try:
                    details = verify(case, record["exit_code"], out, err)
                    passed = True
                except (AssertionError, ValueError, KeyError) as exc:
                    error = str(exc) or type(exc).__name__
                e.data["trials"].append({"case": case, "trial": trial, "exit_code": record["exit_code"], "passed": passed, "verification_error": error, **details})
                print(f"{args.backend} {label}: {'PASS' if passed else 'FAIL'} accepted={details.get('accepted')} reused={details.get('reused')} {error}", flush=True)
    except Exception as exc:
        failure = str(exc)
        print(failure, file=sys.stderr)
    if len(e.data["trials"]) != 40:
        failure = failure or "incomplete matrix"
    fields = ["backend", "case", "trial", "successes", "accepted", "reused", "live_before_cleanup", "live_after_close_idle", "live_after_cleanup", "drained_bytes", "deadline_exceeded", "exit_code", "passed"]
    with (e.dest / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in e.data["trials"]:
            w.writerow({"backend": args.backend, **{k: t.get(k, "") for k in fields if k != "backend"}})
    return 0 if e.seal(failure) else 1


if __name__ == "__main__":
    raise SystemExit(main())
