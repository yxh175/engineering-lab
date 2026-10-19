import csv
import json
import os
import re
import shutil
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parents[1]
sys.path.insert(0, str(ROOT / "shared/scripts"))
from evidence import Evidence, sha

CASES = ["PointerLocal", "PointerRetained", "ValueRetained", "NoInlinePointerLocal", "InterfaceLocal", "InterfaceRetained"]
N = 1000000
ENV = {"CGO_ENABLED": "0", "GOMAXPROCS": "1", "GOGC": "100", "GOMEMLIMIT": "off"}
IMAGE = "golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb"


def checksum(n):
    return sum(i + 3 * i + 7 + (i ^ 0x5A5A) for i in range(n))


def parse(case, config, raw):
    text = raw.decode()
    pattern = rf"^Benchmark{case}(?:-\d+)?\s+(\d+)\s+([\d.]+) ns/op\s+(\d+) B/op\s+(\d+) allocs/op\s*$"
    found = re.findall(pattern, text, re.MULTILINE)
    assert len(found) == 1, "missing or ambiguous benchmark row"
    iterations, ns, byte_count, allocs = found[0]
    assert int(iterations) == N
    logs = re.findall(r"CHECKSUM n=(\d+) value=(\d+)", text)
    assert (str(N), str(checksum(N))) in logs, "final checksum mismatch"
    expected = 1 if case in ["PointerRetained", "NoInlinePointerLocal", "InterfaceRetained"] or (case == "PointerLocal" and config == "noinline") else 0
    assert int(allocs) == expected and int(byte_count) == 24 * expected, "allocation hypothesis not observed"
    return {"iterations": int(iterations), "ns_per_op": float(ns), "bytes_per_op": int(byte_count), "allocs_per_op": int(allocs), "checksum": checksum(N)}


def run(backend):
    os.environ.update(ENV)
    sources = [LAB / "go.mod", LAB / "docker-compose.yml", LAB / "src/record.go", LAB / "src/main.go", LAB / "src/record_test.go", Path(__file__)]
    e = Evidence(LAB, backend, sources, {"cases": CASES, "configs": ["default", "noinline"], "iterations": N,
                                        "repeats_per_case_config": 10, "env": ENV, "race": False, "benchmark_processes": 120})
    work = LAB / ".work" / backend
    work.mkdir(parents=True, exist_ok=True)
    compose = ["docker", "compose", "-p", "engineering-lab-009", "-f", str(LAB / "docker-compose.yml")]
    cid, failure = None, None
    go = shutil.which("go") or "go"

    def argv(args):
        return [go, *args] if backend == "native" else ["docker", "exec", cid, "go", *args]

    try:
        if backend == "docker":
            e.require("docker-version", ["docker", "version"])
            e.require("compose-version", ["docker", "compose", "version"])
            e.require("image-inspect", ["docker", "image", "inspect", IMAGE])
            e.require("startup", compose + ["up", "-d", "--wait"], timeout=120)
            cid = e.require("container-id", compose + ["ps", "-q", "builder"]).decode().strip()
            assert re.fullmatch(r"[a-f0-9]{64}", cid)
            e.require("container-inspect", ["docker", "inspect", cid])
        version = e.require("go-version", argv(["version"]))
        assert b"go1.25.4" in version
        e.require("go-env", argv(["env", "-json", "GOVERSION", "GOOS", "GOARCH", "CGO_ENABLED"]))
        e.require("go-vet", argv(["vet", "./src"]), timeout=180)
        suffix = ".exe" if backend == "native" and os.name == "nt" else ""
        for config in ["default", "noinline"]:
            flags = "-gcflags=-m=2" if config == "default" else "-gcflags=-l -m=2"
            demo = str(work / (config + ".demo" + suffix)) if backend == "native" else "/out/" + config + ".demo"
            binary = str(work / (config + ".test" + suffix)) if backend == "native" else "/out/" + config + ".test"
            e.require(config + "-build-demo", argv(["build", flags, "-o", demo, "./src"]), timeout=180)
            e.require(config + "-build-test", argv(["test", "-c", flags, "-o", binary, "./src"]), timeout=180)
            executable_path = work / (config + ".test" + suffix) if backend == "native" else LAB / ".work/linux" / (config + ".test")
            demo_path = work / (config + ".demo" + suffix) if backend == "native" else LAB / ".work/linux" / (config + ".demo")
            e.data.setdefault("executable_sha256", {})[config] = {"test": sha(executable_path), "demo": sha(demo_path)}
            for case in CASES:
                cmd = [demo, "-case", case, "-n", "100"]
                raw = e.require(config + "-demo-" + case, cmd if backend == "native" else ["docker", "exec", cid, *cmd])
                data = json.loads(raw)
                assert data["checksum"] == checksum(100) and data["record_bytes"] == 24 and data["gomaxprocs"] == 1 and data["go_version"] == "go1.25.4"
                if case.endswith("Retained"):
                    assert data["retained_record"] == {"A": 99, "B": 304, "C": 99 ^ 0x5A5A}
                for trial in range(1, 11):
                    label = f"{config}-{case}-{trial:02d}"
                    cmd = [binary, "-test.run=^$", "-test.bench=^Benchmark" + case + "$", "-test.benchtime=1000000x", "-test.count=1", "-test.cpu=1", "-test.benchmem", "-test.v"]
                    record, out, err = e.run(label, cmd if backend == "native" else ["docker", "exec", cid, *cmd], timeout=45)
                    details, error, passed = {}, "", False
                    try:
                        assert record["exit_code"] == 0
                        details = parse(case, config, out)
                        passed = True
                    except (AssertionError, ValueError) as exc:
                        error = str(exc) or type(exc).__name__
                    e.data["trials"].append({"case": case, "config": config, "trial": trial, "passed": passed, "verification_error": error, **details})
                    print(f"{backend} {label}: {'PASS' if passed else 'FAIL'} allocs={details.get('allocs_per_op')} B={details.get('bytes_per_op')} {error}", flush=True)
        if backend == "docker":
            e.require("shutdown", compose + ["down", "--remove-orphans"], timeout=60)
    except Exception as exc:
        failure = str(exc) or type(exc).__name__
        print(failure, file=sys.stderr)
        if cid:
            e.run("failure-shutdown", compose + ["down", "--remove-orphans"], timeout=60)
    if len(e.data["trials"]) != 120:
        failure = failure or "incomplete matrix"
    fields = ["case", "config", "trial", "passed", "iterations", "ns_per_op", "bytes_per_op", "allocs_per_op", "checksum"]
    with (e.dest / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k: t.get(k, "") for k in fields} for t in e.data["trials"])
    return e.seal(failure)


if __name__ == "__main__":
    passed = run("native")
    if not passed:
        raise SystemExit(1)
    raise SystemExit(0 if run("docker") else 1)
