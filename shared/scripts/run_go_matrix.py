"""Bounded, evidence-preserving runner for lab 001 (stdlib only)."""
import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode(data):
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data or ""


def command(argv, cwd, timeout=60, container=None):
    start = stamp()
    tick = time.monotonic()
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=timeout)
        code, out, err = result.returncode, decode(result.stdout), decode(result.stderr)
    except subprocess.TimeoutExpired as exc:
        code, out, err = 124, decode(exc.stdout), decode(exc.stderr) + f"\nTIMEOUT after {timeout}s\n"
        if container:
            cleanup = subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=30)
            err += "timeout cleanup: " + decode(cleanup.stdout) + decode(cleanup.stderr)
    return {"argv": [str(a) for a in argv], "started_utc": start, "ended_utc": stamp(),
            "elapsed_seconds": time.monotonic() - tick, "exit_code": code, "stdout": out, "stderr": err}


def verify(out, mode):
    rows = [json.loads(line) for line in out.splitlines() if line.strip()]
    assert len(rows) == 7, f"expected 7 samples, got {len(rows)}"
    assert [r["event"] for r in rows] == ["baseline"] + ["wave"] * 5 + ["after_gc"]
    baseline = rows[0]["baseline"]
    for i, row in enumerate(rows):
        wave = 0 if i == 0 else min(i, 5)
        expected = wave * 50 if mode == "bad" else 0
        assert row["mode"] == mode and row["wave"] == wave
        assert row["workers_per_wave"] == 50 and row["baseline"] == baseline
        assert row["bad_blocked"] == expected and row["good_worker_stacks"] == 0, row
        assert row["delta"] == expected and row["goroutines"] == baseline + expected, row
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--backend", choices=["native", "docker"], default="native")
    parser.add_argument("--repeats", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20:
        parser.error("repeats must be 1..20")
    lab = args.lab.resolve()
    if lab.name != "001-go-goroutine-leak":
        parser.error("this schema is specific to lab 001")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + args.backend
    dest = lab / "results" / run_id
    dest.mkdir(parents=True, exist_ok=False)
    (lab / ".work").mkdir(exist_ok=True)
    manifest = {"lab": lab.name, "run_id": run_id, "started_utc": stamp(),
                "backend": args.backend, "host_platform": platform.platform(), "python": sys.version,
                "repeats_per_mode": args.repeats, "waves": 5, "workers_per_wave": 50,
                "source_sha256": {p.relative_to(lab).as_posix(): sha(p) for p in sorted((lab / "src").glob("*.go"))},
                "commands": [], "trials": []}
    project = "engineering-lab-001"
    compose = ["docker", "compose", "-p", project, "-f", str(lab / "docker-compose.yml")]
    binary = lab / ".work" / ("lab001-windows.exe" if os.name == "nt" else "lab001-native")

    def setup(argv, name, timeout=60):
        result = command(argv, lab, timeout)
        (dest / f"{name}.stdout.txt").write_text(result.pop("stdout"), encoding="utf-8")
        (dest / f"{name}.stderr.txt").write_text(result.pop("stderr"), encoding="utf-8")
        manifest["commands"].append(result)
        if result["exit_code"]:
            raise RuntimeError(f"setup command failed: {name}, exit={result['exit_code']}")

    failure = None
    try:
        if args.backend == "native":
            setup(["go", "version"], "go-version")
            setup(["go", "env", "GOOS", "GOARCH", "CGO_ENABLED", "GOMAXPROCS"], "go-env")
            setup(["go", "build", "-trimpath", "-o", str(binary), "./src"], "build", 180)
        else:
            setup(["docker", "version"], "docker-version")
            setup(["docker", "compose", "version"], "compose-version")
            setup(["docker", "image", "inspect", "golang:1.25.4-bookworm"], "image-inspect")
            setup(compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "version"], "go-version")
            setup(compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "env", "GOOS", "GOARCH", "CGO_ENABLED"], "go-env")
            setup(compose + ["run", "--rm", "--no-deps", "--entrypoint", "go", "runner", "build", "-trimpath", "-o", ".work/lab001-linux", "./src"], "build", 180)
        for mode in ["bad", "good"]:
            for trial in range(1, args.repeats + 1):
                label = f"{mode}-{trial:02d}"
                trial_dir = dest / label
                trial_dir.mkdir()
                container = None
                if args.backend == "native":
                    argv = [str(binary), "-mode", mode, "-profile-dir", str(trial_dir)]
                else:
                    container = f"lab001-{run_id.lower()}-{label}"
                    relative = trial_dir.relative_to(lab).as_posix()
                    argv = compose + ["run", "--rm", "--no-deps", "--name", container, "runner", "-mode", mode, "-profile-dir", f"/lab/{relative}"]
                result = command(argv, lab, 45, container)
                stdout = result.pop("stdout")
                (trial_dir / "stdout.jsonl").write_text(stdout, encoding="utf-8")
                (trial_dir / "stderr.txt").write_text(result.pop("stderr"), encoding="utf-8")
                passed, error, last = False, "", {}
                try:
                    assert result["exit_code"] == 0, f"process exit {result['exit_code']}"
                    last = verify(stdout, mode)[-1]
                    profile = (trial_dir / "goroutine.txt").read_text(encoding="utf-8")
                    assert profile.count("\nmain.badWorker(") == (250 if mode == "bad" else 0)
                    assert "\nmain.goodWorker(" not in profile
                    assert (trial_dir / "goroutine.pprof").stat().st_size > 0
                    passed = True
                except (AssertionError, ValueError, OSError) as exc:
                    error = str(exc)
                entry = {"mode": mode, "trial": trial, "passed": passed, "verification_error": error, "last_sample": last, **result}
                manifest["trials"].append(entry)
                print(f"{args.backend} {label}: {'PASS' if passed else 'FAIL'} {error}", flush=True)
    except Exception as exc:
        failure = str(exc)
        print(failure, file=sys.stderr)
    manifest["ended_utc"] = stamp()
    manifest["failure"] = failure
    manifest["all_passed"] = failure is None and len(manifest["trials"]) == args.repeats * 2 and all(t["passed"] for t in manifest["trials"])
    with (dest / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["backend", "mode", "trial", "passed", "baseline", "goroutines", "delta", "bad_blocked", "exit_code"])
        writer.writeheader()
        for t in manifest["trials"]:
            last = t["last_sample"]
            writer.writerow({"backend": args.backend, "mode": t["mode"], "trial": t["trial"], "passed": t["passed"], "exit_code": t["exit_code"], **{k: last.get(k, "") for k in ["baseline", "goroutines", "delta", "bad_blocked"]}})
    manifest["artifact_sha256"] = {p.relative_to(dest).as_posix(): sha(p) for p in sorted(dest.rglob("*")) if p.is_file()}
    (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Evidence: {dest}")
    return 0 if manifest["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
