"""Persistent mysql CLI sessions with raw streams and SQL completion markers.

One in-flight command per session; different sessions may be coordinated by caller.
Stderr is archived per process, not falsely attributed to individual SQL commands.
"""
import json
import queue
import re
import subprocess
import threading
import time
import uuid

from evidence import utc


class MySQLSession:
    def __init__(self, evidence, name, argv):
        assert re.fullmatch(r"[a-zA-Z0-9_-]+", name)
        self.evidence, self.name = evidence, name
        self.directory = evidence.dest / "sessions" / name
        self.directory.mkdir(parents=True, exist_ok=False)
        self.queue = queue.Queue()
        self.pending = None
        self.closed = False
        self.record = {"name": name, "argv": list(argv), "started_utc": utc(), "commands": []}
        evidence.data.setdefault("sessions", []).append(self.record)
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, bufsize=0)
        self.threads = [threading.Thread(target=self._stdout, daemon=True),
                        threading.Thread(target=self._stderr, daemon=True)]
        for thread in self.threads:
            thread.start()

    def _stdout(self):
        with (self.directory / "stdout.txt").open("wb") as archive:
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    self.queue.put(None)
                    break
                archive.write(line)
                archive.flush()
                self.queue.put(line)

    def _stderr(self):
        with (self.directory / "stderr.txt").open("wb") as archive:
            while True:
                data = self.proc.stderr.read(4096)
                if not data:
                    break
                archive.write(data)
                archive.flush()

    def send(self, label, sql):
        if self.closed or self.pending is not None:
            raise RuntimeError(f"{self.name}: closed or already has pending SQL")
        assert re.fullmatch(r"[a-zA-Z0-9_-]+", label)
        target = self.evidence.dest / label
        target.mkdir(exist_ok=False)
        marker = "ENG_END_" + uuid.uuid4().hex
        text = sql.rstrip() + "\nSELECT '" + marker + "';\n"
        raw = text.encode("utf-8")
        (target / "input.sql").write_bytes(raw)
        record = {"label": label, "marker": marker, "started_utc": utc(), "completed": False}
        self.record["commands"].append(record)
        self.pending = {"target": target, "marker": marker.encode(), "record": record,
                        "tick": time.monotonic(), "lines": []}
        self.proc.stdin.write(raw)
        self.proc.stdin.flush()
        return record

    def finish(self, timeout=15):
        if self.pending is None:
            raise RuntimeError(f"{self.name}: no pending SQL")
        p = self.pending
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    line = self.queue.get(timeout=max(.001, deadline-time.monotonic()))
                except queue.Empty:
                    raise TimeoutError(f"{self.name}: SQL marker timeout, process poll={self.proc.poll()}")
                if line is None:
                    raise RuntimeError(f"{self.name}: stdout EOF before marker, process poll={self.proc.poll()}")
                p["lines"].append(line)
                if line.rstrip(b"\r\n") == p["marker"]:
                    p["record"]["completed"] = True
                    return b"".join(p["lines"][:-1])
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"{self.name}: SQL marker timeout")
        finally:
            p["record"].update({"ended_utc": utc(), "elapsed_seconds": time.monotonic()-p["tick"]})
            (p["target"] / "stdout.txt").write_bytes(b"".join(p["lines"]))
            (p["target"] / "command.json").write_text(json.dumps(p["record"], indent=2)+"\n", encoding="utf-8", newline="\n")
            if p["record"]["completed"]:
                self.pending = None

    def execute(self, label, sql, timeout=15):
        self.send(label, sql)
        return self.finish(timeout)

    def close(self):
        if self.closed:
            return self.record["exit_code"]
        self.closed = True
        if self.proc.poll() is None:
            self.proc.stdin.close()  # EOF causes the batch client to end its session.
        forced = False
        try:
            code = self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            code = self.proc.wait(timeout=5)
            forced = True
        for thread in self.threads:
            thread.join(timeout=5)
        self.record.update({"ended_utc": utc(), "exit_code": code, "forced_host_client_kill": forced,
                            "all_sql_markers_completed": all(x["completed"] for x in self.record["commands"]),
                            "stderr_bytes": (self.directory / "stderr.txt").stat().st_size})
        (self.directory / "session.json").write_text(json.dumps(self.record, indent=2)+"\n", encoding="utf-8", newline="\n")
        return code
