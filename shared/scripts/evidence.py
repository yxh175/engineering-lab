"""Stdlib evidence capture; preserve raw bytes, bound commands, seal each run."""
import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Evidence:
    def __init__(self, lab, backend, source_paths, parameters=None):
        self.lab = Path(lab).resolve()
        self.root = self.lab.parents[1]
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + backend
        self.dest = self.lab / "results" / run_id
        self.dest.mkdir(parents=True, exist_ok=False)
        self.data = {"lab": self.lab.name, "run_id": run_id, "started_utc": utc(), "backend": backend,
                     "host_platform": platform.platform(), "python": sys.version, "parameters": parameters or {},
                     "source_sha256": {Path(p).relative_to(self.lab).as_posix(): sha(p) for p in source_paths},
                     "shared_source_sha256": {"shared/scripts/evidence.py": sha(Path(__file__))},
                     "commands": [], "trials": []}

    def run(self, label, argv, cwd=None, timeout=60, container=None, stdin=None):
        start, tick = utc(), time.monotonic()
        cleanup = None
        try:
            r = subprocess.run([str(x) for x in argv], cwd=cwd or self.lab, input=stdin, capture_output=True, timeout=timeout)
            code, stdout, stderr = r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired as exc:
            code, stdout, stderr = 124, exc.stdout or b"", exc.stderr or b""
            stderr += f"\nRUNNER_TIMEOUT after {timeout}s\n".encode()
            if container:
                c = subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=30)
                cleanup = {"container": container, "exit_code": c.returncode,
                           "stdout": c.stdout.decode(errors="replace"), "stderr": c.stderr.decode(errors="replace")}
        target = self.dest / label
        target.mkdir(parents=True, exist_ok=False)
        (target / "stdout.txt").write_bytes(stdout)
        (target / "stderr.txt").write_bytes(stderr)
        record = {"label": label, "argv": [str(x) for x in argv], "started_utc": start, "ended_utc": utc(),
                  "elapsed_seconds": time.monotonic() - tick, "exit_code": code, "timeout_cleanup": cleanup}
        self.data["commands"].append(record)
        return record, stdout, stderr

    def require(self, label, argv, **kwargs):
        record, out, err = self.run(label, argv, **kwargs)
        if record["exit_code"] != 0:
            raise RuntimeError(f"{label} exit {record['exit_code']}; raw evidence in {self.dest / label}")
        return out

    def seal(self, failure=None):
        self.data["ended_utc"] = utc()
        self.data["failure"] = failure
        self.data["all_passed"] = failure is None and bool(self.data["trials"]) and all(t["passed"] for t in self.data["trials"])
        self.data["artifact_sha256"] = {p.relative_to(self.dest).as_posix(): sha(p) for p in sorted(self.dest.rglob("*")) if p.is_file()}
        (self.dest / "manifest.json").write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"Evidence: {self.dest}")
        return self.data["all_passed"]
