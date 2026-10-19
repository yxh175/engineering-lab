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

CASES = json.loads((LAB / "src/cases.json").read_text(encoding="utf-8"))
ENV = {"CGO_ENABLED": "0", "GOMAXPROCS": "1", "GOGC": "off", "GOMEMLIMIT": "off"}
IMAGE = "golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb"


def verify(config, code, raw):
    d = json.loads(raw)
    assert d["case"] == config["case"]
    assert d["go_version"] == "go1.25.4" and d["goarch"] == "amd64" and d["gomaxprocs"] == 1
    assert d["gc_percent"] == -1 and d["memory_limit"] == 2**63 - 1
    assert d["seed_id"] == 1 and d["seed_value"] == 314159
    assert code == config["exit"] == d["exit_code"]
    for key in ["found", "returned_id", "returned_value", "new_calls"]:
        assert d[key] == config[key], f"{key}: {d[key]} != {config[key]}"
    delta = d["gc_final"] - d["gc_baseline"]
    assert delta == config["gc_delta"]
    assert len(d["gc_points"]) == config["gc_delta"] + 1
    for step, point in enumerate(d["gc_points"]):
        assert point["step"] == step and point["num_gc"] == d["gc_baseline"] + step
    if config["case"] == "pool-two-gc":
        assert d["error"] == "required_object_missing"
    else:
        assert not d["error"]
    if config["case"] == "pool-refresh-two-gc":
        assert d["intermediate_id"] == 1
    if config["case"] == "pool-new-two-gc":
        assert d["initial_new_calls"] == 1 and d["value_before_reset"] == 0
        assert d["completed"] == 1 and d["checksum"] == 42
    elif config["case"] == "pool-new-hot":
        assert d["initial_new_calls"] == 1 and d["completed"] == d["reuse_hits"] == 1000
        assert d["checksum"] == sum(range(1000))
    else:
        assert d["initial_new_calls"] == 0
    return {"gc_delta": delta, "original_id_returned": d["found"] and d["returned_id"] == d["seed_id"], **d}


def run(backend):
    os.environ.update(ENV)
    e = Evidence(LAB, backend, [LAB / "go.mod", LAB / "docker-compose.yml", LAB / "src/main.go", LAB / "src/cache.go", LAB / "src/cases.json", Path(__file__)],
                 {"cases": [c["case"] for c in CASES], "repeats_per_case": 10, "env": ENV,
                  "warm_gc_before_seed": True, "race": False, "single_caller": True, "expected_processes": 70})
    work = LAB / ".work" / backend
    work.mkdir(parents=True, exist_ok=True)
    compose = ["docker", "compose", "-p", "engineering-lab-010", "-f", str(LAB / "docker-compose.yml")]
    go = shutil.which("go") or "go"
    cid, failure = None, None

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
        assert b"go1.25.4" in e.require("go-version", argv(["version"]))
        e.require("go-env", argv(["env", "-json", "GOVERSION", "GOOS", "GOARCH", "CGO_ENABLED"]))
        e.require("go-vet", argv(["vet", "./src"]), timeout=180)
        suffix = ".exe" if backend == "native" and os.name == "nt" else ""
        executable = str(work / ("pool-demo" + suffix)) if backend == "native" else "/out/pool-demo"
        e.require("go-build", argv(["build", "-o", executable, "./src"]), timeout=180)
        binary_path = work / ("pool-demo" + suffix) if backend == "native" else LAB / ".work/linux/pool-demo"
        e.data["executable_sha256"] = sha(binary_path)
        for config in CASES:
            for trial in range(1, 11):
                label = f"{config['case']}-{trial:02d}"
                cmd = [executable, "-case", config["case"]]
                record, out, err = e.run(label, cmd if backend == "native" else ["docker", "exec", cid, *cmd], timeout=30)
                passed, details, error = False, {}, ""
                try:
                    details = verify(config, record["exit_code"], out)
                    assert details["goos"] == ("linux" if backend == "docker" else ("windows" if os.name == "nt" else "linux"))
                    passed = True
                except (AssertionError, ValueError, KeyError) as exc:
                    error = str(exc) or type(exc).__name__
                e.data["trials"].append({"case": config["case"], "trial": trial, "passed": passed, "verification_error": error, "process_exit": record["exit_code"], **details})
                print(f"{backend} {label}: {'PASS' if passed else 'FAIL'} GC={details.get('gc_delta')} ID={details.get('returned_id')} New={details.get('new_calls')} exit={record['exit_code']} {error}", flush=True)
        if backend == "docker":
            e.require("shutdown", compose + ["down", "--remove-orphans"], timeout=60)
    except Exception as exc:
        failure = str(exc) or type(exc).__name__
        print(failure, file=sys.stderr)
        if cid:
            e.run("failure-shutdown", compose + ["down", "--remove-orphans"], timeout=60)
    if len(e.data["trials"]) != 70:
        failure = failure or "incomplete matrix"
    fields = ["case", "trial", "passed", "process_exit", "gc_delta", "original_id_returned", "returned_id", "returned_value", "initial_new_calls", "new_calls", "completed", "reuse_hits", "checksum"]
    with (e.dest / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k: t.get(k, "") for k in fields} for t in e.data["trials"])
    return e.seal(failure)


if __name__ == "__main__":
    if not run("native"):
        raise SystemExit(1)
    raise SystemExit(0 if run("docker") else 1)
