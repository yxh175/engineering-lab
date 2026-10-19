import csv
import json
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parents[1]
sys.path.insert(0, str(ROOT / "shared/scripts"))
from evidence import Evidence

CASES = ["bad-unclosed", "bad-deferred", "good-close"]
IMAGE = "golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb"


def verify(case, limit, code, out, err):
    rows = [json.loads(s) for s in out.decode().splitlines() if s]
    first, last = rows[0], rows[-1]
    baseline = first["fd_count"]
    assert first["event"] == "baseline" and last["event"] == "after-cleanup"
    assert all(r["case"] == case and r["soft_limit"] == limit and r["baseline"] == baseline for r in rows)
    assert all(r["hard_limit"] == first["hard_limit"] and r["go_version"] == "go1.25.4" for r in rows)
    assert last["fd_count"] == baseline, "FDs did not return to baseline"
    assert len(first["fds"]) == baseline and len(last["fds"]) == baseline
    if case.startswith("bad-"):
        assert code == 3, f"wrong demo exit {code}"
        faults = [r for r in rows if r["event"] == "open-error"]
        assert len(faults) == 1 and faults[0]["errno"] == 24
        fault = faults[0]
        assert fault["fd_count"] == limit and len(fault["fds"]) == limit
        assert max(f["fd"] for f in fault["fds"]) == limit - 1
        assert fault["successes"] == limit - baseline and fault["failed_attempt"] == limit - baseline + 1
        assert b"too many open files" in err and "too many open files" in fault["error"]
        assert last["peak_observed"] == limit
        for r in rows:
            if r["event"] == "opened":
                assert r["fd_count"] == baseline + r["successes"]
    else:
        assert code == 0 and not err and last["successes"] == 512 and last["failed_attempt"] == 0
        assert last["errno"] == 0 and last["peak_observed"] == baseline + 1
        assert all(r["fd_count"] == baseline + 1 for r in rows if r["event"] == "opened")
        assert all(r["fd_count"] == baseline for r in rows if r["event"] == "after-close")
    return {"baseline": baseline, "peak": last["peak_observed"], "after_cleanup": last["fd_count"],
            "successes": last["successes"], "failed_attempt": last["failed_attempt"], "errno": last["errno"]}


def main():
    sources = sorted((LAB / "src").glob("*.go")) + [LAB / "go.mod", LAB / "docker-compose.yml", Path(__file__)]
    e = Evidence(LAB, "docker", sources, {"cases": CASES, "soft_limits": [64, 128], "iterations": 512, "repeats_per_group": 10})
    (LAB / ".work").mkdir(exist_ok=True)
    compose = ["docker", "compose", "-p", "engineering-lab-004", "-f", str(LAB / "docker-compose.yml")]
    failure = None
    try:
        e.require("docker-version", ["docker", "version"])
        e.require("compose-version", ["docker", "compose", "version"])
        e.require("image-inspect", ["docker", "image", "inspect", IMAGE])
        e.require("kernel", compose + ["run", "--rm", "--no-deps", "--entrypoint", "uname", "runner", "-a"])
        e.require("go-version", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "version"])
        e.require("go-env", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "env", "GOOS", "GOARCH", "CGO_ENABLED"])
        e.require("build", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "build", "-trimpath", "-o", ".work/lab004-linux", "./src"], timeout=180)
        e.require("go-vet", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "vet", "./src"], timeout=180)
        for limit in [64, 128]:
            for case in CASES:
                for trial in range(1, 11):
                    label = f"limit{limit}-{case}-{trial:02d}"
                    name = f"lab004-{e.data['run_id'].lower()}-{label}"
                    argv = compose + ["run", "--rm", "--no-deps", "--name", name, "runner", "-case", case, "-limit", str(limit)]
                    record, out, err = e.run(label, argv, timeout=30, container=name)
                    passed, details, error = False, {}, ""
                    try:
                        details = verify(case, limit, record["exit_code"], out, err)
                        passed = True
                    except (AssertionError, ValueError, KeyError) as exc:
                        error = str(exc) or type(exc).__name__
                    e.data["trials"].append({"case": case, "limit": limit, "trial": trial, "exit_code": record["exit_code"], "passed": passed, "verification_error": error, **details})
                    print(f"{label}: {'PASS' if passed else 'FAIL'} peak={details.get('peak')} errno={details.get('errno')} {error}", flush=True)
    except Exception as exc:
        failure = str(exc)
        print(failure, file=sys.stderr)
    if len(e.data["trials"]) != 60:
        failure = failure or "incomplete matrix"
    fields = ["case", "limit", "trial", "baseline", "peak", "after_cleanup", "successes", "failed_attempt", "errno", "exit_code", "passed"]
    with (e.dest / "summary.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in e.data["trials"]:
            w.writerow({k: t.get(k, "") for k in fields})
    return 0 if e.seal(failure) else 1


if __name__ == "__main__":
    raise SystemExit(main())
