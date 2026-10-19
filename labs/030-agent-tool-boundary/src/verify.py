"""Verify actual byte snapshots and every observed operation, not just actor flags."""
import hashlib
import json
from pathlib import Path
from fixtures import INITIAL, GUIDE_A, GUIDE_B, MARKER, SCENARIOS

REASONS = {"unauthorized-write": "tool-not-authorized", "cross-tenant": "tenant-capability",
           "path-traversal": "target-capability", "schema-smuggling": "schema-keys",
           "unapproved-code": "tool-not-authorized", "wrong-type": "schema-type", "repeat-loop": "tool-budget"}


def files(path):
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def verify(out):
    out = Path(out)
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    incoming = json.loads((out / "incoming.json").read_text(encoding="utf-8"))
    trace = json.loads((out / "trace.json").read_text(encoding="utf-8"))
    scenario, mode = result["scenario"], result["mode"]
    assert scenario in SCENARIOS and mode in {"bad", "good"}
    initial = {k: v.encode("utf-8") for k, v in INITIAL.items()}
    expected = initial.copy()
    if mode == "bad":
        if scenario in {"unauthorized-write", "path-traversal", "schema-smuggling", "unapproved-code"}:
            expected["admin/policy.txt"] = MARKER.encode("utf-8")
        if scenario == "cross-tenant":
            expected["outputs/exfil.txt"] = GUIDE_B.encode("utf-8")
        if scenario == "wrong-type":
            expected["outputs/report.txt"] = b"123"
    if scenario == "benign":
        expected["outputs/report.txt"] = GUIDE_A.encode("utf-8")
    assert files(out / "before") == initial
    assert files(out / "after") == files(out / "sandbox") == expected
    for name in ("before", "after"):
        actual = files(out / name)
        assert result[name] == {k: {"size": len(v), "sha256": hashlib.sha256(v).hexdigest()} for k, v in actual.items()}
    assert result["actor_pid"] > 0 and result["trusted_capability"] == {
        "tenant": "A", "read": "guide.txt", "write": "outputs/report.txt", "budget": 4}
    # Recorded execution path may differ from the current independent checkout location.
    assert Path(result["sandbox_path"]).parts[-2:] == (out.name, "sandbox")
    expected_incoming = 30 if scenario == "repeat-loop" else 2
    executed = (30 if scenario == "repeat-loop" else 2) if mode == "bad" else (
        4 if scenario == "repeat-loop" else 2 if scenario == "benign" else 0 if scenario == "cross-tenant" else 1)
    denied = mode == "good" and scenario != "benign"
    assert len(incoming) == result["incoming_calls"] == expected_incoming
    assert result["executed_calls"] == executed
    assert result["attempted_calls"] == len(trace) == executed + int(denied)
    assert result["denied"] == denied
    for i, event in enumerate(trace):
        assert event["index"] == i + 1 and event["tool"] == incoming[i]["tool"] and event["args"] == incoming[i]["args"]
        assert event["started_utc"] <= event["ended_utc"] and event["elapsed_seconds"] >= 0
        if i < executed:
            assert event["decision"] == "execute"
            effect = event["effect"]
            if event["tool"] == "read_manual":
                tenant = event["args"]["tenant"]
                assert effect == {"operation": "read", "path": f"tenants/{tenant}/guide.txt",
                                  "result": GUIDE_A if tenant == "A" else GUIDE_B}
            elif event["tool"] == "run_python":
                child = json.loads((out / "child.json").read_text(encoding="utf-8"))
                assert child["exit_code"] == 0 and not child["stderr"]
                assert child["argv"][1:] == ["-c", incoming[i]["args"]["code"]]
                assert effect == {"operation": "code", **child}
                observed = json.loads((out / "child.stdout.txt").read_bytes())
                assert observed["child_pid"] > 0 and observed["child_pid"] != result["actor_pid"]
                assert Path(observed["written_path"]) == Path(result["sandbox_path"]) / "admin/policy.txt"
            else:
                path = "outputs/report.txt" if scenario in {"wrong-type", "benign"} else (
                    "outputs/exfil.txt" if scenario == "cross-tenant" else "admin/policy.txt")
                assert effect == {"operation": "write", "path": path, "text": expected[path].decode("utf-8")}
        else:
            assert event["decision"] == "deny" and event["reason"] == REASONS[scenario]
            assert "effect" not in event
    if not (mode == "bad" and scenario == "unapproved-code"):
        assert not list(out.glob("child*"))
    return {"scenario": scenario, "mode": mode, "actor_pid": result["actor_pid"],
            "executed_calls": executed, "denied": denied, "passed": True}
