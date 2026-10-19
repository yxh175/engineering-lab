"""Actual filesystem tool execution. Experiment containment != application authorization."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from fixtures import INITIAL, SCENARIOS, trajectory

sys.stdout.reconfigure(encoding="utf-8")


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def utc():
    return datetime.now(timezone.utc).isoformat()


def snapshot(sandbox, target):
    target.mkdir(exist_ok=False)
    files = {}
    for path in sorted(sandbox.rglob("*")):
        if path.is_file():
            key = path.relative_to(sandbox).as_posix()
            raw = path.read_bytes()
            copy = target / key
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(raw)
            files[key] = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    return files


class Denied(Exception):
    pass


class Executor:
    # Trusted session capability, fixed independently of retrieved text and tool arguments.
    def __init__(self, sandbox, outdir, mode):
        self.sandbox, self.outdir, self.mode = sandbox, outdir, mode
        self.executed = 0
        self.last_result = ""

    def contained(self, path):
        resolved = path.resolve()
        if not resolved.is_relative_to(self.sandbox):
            raise RuntimeError("experiment-envelope-escape")
        return resolved

    def validate(self, tool, args):
        if self.executed >= 4:
            raise Denied("tool-budget")
        schemas = {"read_manual": {"tenant", "name"}, "write_report": {"path", "text"}}
        if tool not in schemas:
            raise Denied("tool-not-authorized")
        if type(args) is not dict or set(args) != schemas[tool]:
            raise Denied("schema-keys")
        if any(type(v) is not str for v in args.values()):
            raise Denied("schema-type")
        if any(len(v) > 2048 for v in args.values()):
            raise Denied("schema-size")
        if tool == "read_manual" and (args["tenant"], args["name"]) != ("A", "guide.txt"):
            raise Denied("tenant-capability")
        if tool == "write_report":
            resolved = self.contained(self.sandbox / "outputs" / args["path"])
            if args["path"] != "report.txt" or resolved != self.sandbox / "outputs/report.txt":
                raise Denied("target-capability")

    def dispatch(self, tool, args):
        if self.mode == "good":
            self.validate(tool, args)
        if tool == "read_manual":
            path = self.contained(self.sandbox / "tenants" / args["tenant"] / args["name"])
            result = path.read_text(encoding="utf-8")
            effect = {"operation": "read", "path": path.relative_to(self.sandbox).as_posix(), "result": result}
        elif tool in {"write_report", "write_file"}:
            base = self.sandbox / "outputs" if tool == "write_report" else self.sandbox
            path = self.contained(base / args.get("destination", args["path"]))
            text = args["text"]
            if text == "$last_result":
                text = self.last_result
            text = str(text)  # Bad accepts/coerces integers; Good has already validated strict strings.
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            result = "written"
            effect = {"operation": "write", "path": path.relative_to(self.sandbox).as_posix(), "text": text}
        elif tool == "run_python":
            argv = [sys.executable, "-c", args["code"]]
            child = subprocess.run(argv, cwd=self.sandbox, capture_output=True, timeout=10)
            (self.outdir / "child.stdout.txt").write_bytes(child.stdout)
            (self.outdir / "child.stderr.txt").write_bytes(child.stderr)
            meta = {"argv": argv, "exit_code": child.returncode,
                    "stdout": child.stdout.decode("utf-8"), "stderr": child.stderr.decode("utf-8")}
            save(self.outdir / "child.json", meta)
            if child.returncode != 0:
                raise RuntimeError("controlled-child-failed")
            result = "code-executed"
            effect = {"operation": "code", **meta}
        else:
            raise RuntimeError("unknown-fixture-tool")
        self.executed += 1
        self.last_result = result
        return effect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["bad", "good"], required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()
    out = args.outdir.resolve()
    lab = Path(__file__).resolve().parents[1]
    if not out.is_relative_to(lab / "results"):
        raise RuntimeError("outdir must be under this lab/results")
    out.mkdir(parents=True, exist_ok=False)
    sandbox = out / "sandbox"
    sandbox.mkdir()
    (sandbox / "outputs").mkdir()
    for name, text in INITIAL.items():
        path = sandbox / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    before = snapshot(sandbox, out / "before")
    calls = trajectory(args.scenario, sandbox)
    save(out / "incoming.json", calls)
    executor = Executor(sandbox, out, args.mode)
    trace = []
    for index, call in enumerate(calls, 1):
        event = {"index": index, "started_utc": utc(), "tool": call["tool"], "args": call["args"]}
        tick = time.monotonic()
        try:
            event.update(decision="execute", effect=executor.dispatch(call["tool"], call["args"]))
        except Denied as exc:
            event.update(decision="deny", reason=str(exc))
        event.update(ended_utc=utc(), elapsed_seconds=time.monotonic() - tick)
        trace.append(event)
        if event["decision"] == "deny":
            break
    after = snapshot(sandbox, out / "after")
    save(out / "trace.json", trace)
    result = {"mode": args.mode, "scenario": args.scenario, "actor_pid": os.getpid(),
              "python": sys.version, "platform": platform.platform(), "sandbox_path": str(sandbox), "incoming_calls": len(calls),
              "attempted_calls": len(trace), "executed_calls": executor.executed,
              "denied": trace[-1]["decision"] == "deny", "before": before, "after": after,
              "trusted_capability": {"tenant": "A", "read": "guide.txt", "write": "outputs/report.txt", "budget": 4}}
    save(out / "result.json", result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
