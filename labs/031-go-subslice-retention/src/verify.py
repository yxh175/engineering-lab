"""Recompute payload/MemStats deltas and actual pprof inuse samples attributed to retain."""
import hashlib
import re

SIZE = 32 << 20


def profile_inuse(raw):
    # Parse actual `go tool pprof -raw`, not printed top percentages.
    locations = {int(m.group(1)) for line in raw.splitlines()
                 if (m := re.match(r"\s*(\d+):", line)) and "main.retain" in line}
    total = 0
    for line in raw.splitlines():
        m = re.match(r"\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+):\s*(.*)$", line)
        if m and set(map(int, m.group(5).split())) & locations:
            total += int(m.group(4))
    return total


def verify(result, profiles):
    mode = result["case"]
    assert mode in {"subslice", "cap-limited", "copied"}
    assert result["go"] == "go1.25.4" and result["os"] == "windows" and result["arch"] == "amd64"
    assert result["pid"] > 0 and result["gomaxprocs"] == 1 and result["mem_profile_rate"] == 1
    assert result["array_bytes"] == SIZE
    baseline, live, released = result["samples"]
    assert [s["stage"] for s in result["samples"]] == ["baseline", "held", "released"]
    expected = bytes((SIZE//2+i) % 251 for i in range(32))
    assert live["len"] == 32 and live["payload_hex"] == expected.hex()
    assert live["sha256"] == hashlib.sha256(expected).hexdigest()
    assert live["cap"] == SIZE//2 if mode == "subslice" else live["cap"] >= 32
    if mode == "cap-limited":
        assert live["cap"] == 32
    assert baseline["len"] == released["len"] == 0 and baseline["cap"] == released["cap"] == 0
    assert released["payload_hex"] == "" and released["sha256"] == hashlib.sha256(b"").hexdigest()
    assert live["num_gc"] >= baseline["num_gc"] + 2 and released["num_gc"] >= live["num_gc"] + 2
    delta = live["heap_alloc"]-baseline["heap_alloc"]
    assert delta >= SIZE if mode != "copied" else abs(delta) < 1 << 20
    assert abs(released["heap_alloc"]-baseline["heap_alloc"]) < 1 << 20
    inuse = {stage: profile_inuse(raw) for stage, raw in profiles.items()}
    assert inuse["baseline"] == inuse["released"] == 0
    assert inuse["held"] >= SIZE if mode != "copied" else 0 < inuse["held"] <= 4096
    return {"case": mode, "pid": result["pid"], "len": live["len"], "cap": live["cap"],
            "heap_alloc_delta": delta, "heap_after_release_delta": released["heap_alloc"]-baseline["heap_alloc"],
            "profile_retain_inuse": inuse, "passed": True}
