import csv
import json
import re
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parents[1]
sys.path.insert(0, str(ROOT / "shared/scripts"))
from evidence import Evidence

CASES = ["bad-barrier", "bad-correct", "good-atomic"]
IMAGE = "golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb"


def verify(case, build, code, out, err):
    rows = [json.loads(s) for s in out.decode("utf-8").splitlines() if s]
    assert len(rows) == 1
    r = rows[0]
    assert r["case"] == case and r["workers"] == 64 and r["expected"] == 64
    assert r["os"] == "linux" and r["arch"] == "amd64" and r["go_version"] == "go1.25.4"
    assert r["race_enabled"] == (build == "race")
    assert r["gomaxprocs"] == (1 if case == "bad-correct" else 2)
    assert r["actual"] == (1 if case == "bad-barrier" else 64), r
    detected = b"WARNING: DATA RACE" in err
    if build == "race" and case.startswith("bad-"):
        assert code == 66 and detected, "missing race header or configured exitcode"
        assert re.search(rb"Found [1-9][0-9]* data race\(s\)", err), "missing Go race final report count"
        assert b"Previous " in err and b"created at:" in err, "missing conflict or goroutine creation stacks"
        assert (b"main.badBarrier" if case == "bad-barrier" else b"main.badCorrect") in err, "missing case-specific stack"
    else:
        assert code == 0 and not detected and not err, (code, err)
    return {**r, "detected": detected, "report_count": err.count(b"WARNING: DATA RACE")}


def main():
    sources = sorted((LAB / "src").glob("*.go")) + [LAB / "go.mod", LAB / "docker-compose.yml", Path(__file__)]
    e = Evidence(LAB, "docker", sources, {"cases": CASES, "builds": ["normal", "race"], "repeats_per_group": 10,
                                           "workers": 64, "GORACE": "exitcode=66 halt_on_error=0 atexit_sleep_ms=0"})
    (LAB / ".work").mkdir(exist_ok=True)
    compose = ["docker", "compose", "-p", "engineering-lab-003", "-f", str(LAB / "docker-compose.yml")]
    failure = None
    try:
        e.require("docker-version", ["docker", "version"])
        e.require("compose-version", ["docker", "compose", "version"])
        e.require("image-inspect", ["docker", "image", "inspect", IMAGE])
        e.require("go-version", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "version"])
        env = e.require("go-env", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "env", "GOOS", "GOARCH", "CGO_ENABLED", "CC"])
        assert env.decode().splitlines()[:3] == ["linux", "amd64", "1"]
        e.require("gcc-version", compose + ["run", "--rm", "--no-deps", "--entrypoint", "gcc", "runner", "--version"])
        e.require("gorace-env", compose + ["run", "--rm", "--no-deps", "--entrypoint", "printenv", "runner", "GORACE"])
        for build in ["normal", "race"]:
            flags = ["-race"] if build == "race" else []
            e.require(f"build-{build}", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "build", *flags, "-trimpath", "-o", f".work/lab003-{build}", "./src"], timeout=240)
            for case in CASES:
                for trial in range(1, 11):
                    label = f"{build}-{case}-{trial:02d}"
                    container = f"lab003-{e.data['run_id'].lower()}-{label}"
                    argv = compose + ["run", "--rm", "--no-deps", "--name", container, "--entrypoint", f"/lab/.work/lab003-{build}", "runner", "-case", case]
                    record, out, err = e.run(label, argv, timeout=30, container=container)
                    passed, details, error = False, {}, ""
                    try:
                        details = verify(case, build, record["exit_code"], out, err)
                        passed = True
                    except (AssertionError, ValueError) as exc:
                        error = str(exc)
                    e.data["trials"].append({"build": build, "case": case, "trial": trial, "exit_code": record["exit_code"], "passed": passed, "verification_error": error, **details})
                    print(f"{label}: {'PASS' if passed else 'FAIL'} actual={details.get('actual')} exit={record['exit_code']} {error}", flush=True)
    except Exception as exc:
        failure = str(exc)
        print(failure, file=sys.stderr)
    if len(e.data["trials"]) != 60:
        failure = failure or "incomplete matrix"
    fields = ["build", "case", "trial", "actual", "expected", "gomaxprocs", "detected", "report_count", "exit_code", "passed"]
    with (e.dest / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for trial in e.data["trials"]:
            w.writerow({k: trial.get(k, "") for k in fields})
    return 0 if e.seal(failure) else 1


if __name__ == "__main__":
    raise SystemExit(main())
