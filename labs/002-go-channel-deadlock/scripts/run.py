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

CASES = ["bad-unbuffered", "bad-full-buffer", "good-concurrent", "good-buffered"]
IMAGE = "golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb"


def verify(case, code, out, err):
    events = [json.loads(s) for s in out.decode("utf-8").splitlines() if s]
    if case.startswith("bad-"):
        fn = "badUnbuffered" if case == "bad-unbuffered" else "badFullBuffer"
        assert code == 2, f"wrong binary exit: {code}"
        assert b"fatal error: all goroutines are asleep - deadlock!" in err
        assert b"[chan send]" in err and f"main.{fn}".encode() in err
        names = [e["event"] for e in events]
        assert names == (["before-send"] if case == "bad-unbuffered" else ["buffer-filled", "before-second-send"])
        assert all(e["scenario"] == case for e in events)
        return {"outcome": "deadlock", "received": False, "recovered": False, "events": names}
    assert code == 0 and not err, f"exit={code}, stderr={err!r}"
    assert [e["event"] for e in events] == ["before-send", "after-send", "received"]
    assert all(e["scenario"] == case and e["value"] == 42 for e in events)
    assert all(e["capacity"] == (1 if case == "good-buffered" else 0) for e in events)
    return {"outcome": "received", "received": True, "recovered": False, "events": [e["event"] for e in events]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["native", "docker"], default="native")
    args = parser.parse_args()
    sources = sorted((LAB / "src").glob("*.go")) + [LAB / "go.mod", LAB / "docker-compose.yml", Path(__file__)]
    e = Evidence(LAB, args.backend, sources, {"repeats_per_case": 10, "cases": CASES})
    (LAB / ".work").mkdir(exist_ok=True)
    compose = ["docker", "compose", "-p", "engineering-lab-002", "-f", str(LAB / "docker-compose.yml")]
    binary = LAB / ".work" / ("lab002-native.exe" if os.name == "nt" else "lab002-native")
    failure = None
    try:
        if args.backend == "native":
            e.require("go-version", ["go", "version"])
            e.require("go-env", ["go", "env", "GOOS", "GOARCH", "CGO_ENABLED"])
            e.require("build", ["go", "build", "-trimpath", "-o", str(binary), "./src"], timeout=180)
        else:
            e.require("docker-version", ["docker", "version"])
            e.require("compose-version", ["docker", "compose", "version"])
            e.require("image-inspect", ["docker", "image", "inspect", IMAGE])
            e.require("go-version", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "version"])
            e.require("go-env", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "env", "GOOS", "GOARCH", "CGO_ENABLED"])
            e.require("build", compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "build", "-trimpath", "-o", ".work/lab002-linux", "./src"], timeout=180)
        for case in CASES:
            for trial in range(1, 11):
                label = f"{case}-{trial:02d}"
                container = None
                argv = [str(binary), "-case", case]
                if args.backend == "docker":
                    container = f"lab002-{e.data['run_id'].lower()}-{label}"
                    argv = compose + ["run", "--rm", "--no-deps", "--name", container, "runner", "-case", case]
                record, out, err = e.run(label, argv, timeout=20, container=container)
                passed, details, error = False, {}, ""
                try:
                    details = verify(case, record["exit_code"], out, err)
                    passed = True
                except (AssertionError, ValueError) as exc:
                    error = str(exc)
                e.data["trials"].append({"case": case, "trial": trial, "exit_code": record["exit_code"], "passed": passed, "verification_error": error, **details})
                print(f"{args.backend} {label}: {'PASS' if passed else 'FAIL'} exit={record['exit_code']} {error}", flush=True)
    except Exception as exc:
        failure = str(exc)
        print(failure, file=sys.stderr)
    if len(e.data["trials"]) != 40:
        failure = failure or "incomplete matrix"
    with (e.dest / "summary.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["backend", "case", "trial", "exit_code", "passed", "outcome", "received", "recovered"])
        w.writeheader()
        for t in e.data["trials"]:
            w.writerow({"backend": args.backend, **{k: t.get(k, "") for k in w.fieldnames if k != "backend"}})
    return 0 if e.seal(failure) else 1


if __name__ == "__main__":
    raise SystemExit(main())
