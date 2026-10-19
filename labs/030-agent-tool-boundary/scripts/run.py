"""160 fresh actors, actual private fixture operations, same trajectories for both modes."""
from pathlib import Path
import json
import sys

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parents[1]
sys.path[:0] = [str(ROOT / "shared/scripts"), str(LAB / "src")]
from evidence import Evidence
from fixtures import SCENARIOS
from verify import verify

sources = [LAB / x for x in ("src/fixtures.py", "src/actor.py", "src/verify.py", "scripts/run.py")]
e = Evidence(LAB, "tool-boundary-replay", sources, {"rounds": 10, "scenarios": SCENARIOS,
    "modes": ["bad", "good"], "good_budget": 4, "loop_trajectory_calls": 30,
    "llm_invoked": False, "network_invoked": False, "fake_secrets_only": True})
failure = None
try:
    for round_id in range(1, 11):
        for scenario in SCENARIOS:
            for mode in ("bad", "good"):
                label = f"r{round_id:02}-{scenario}-{mode}"
                out = e.dest / "actors" / label
                raw = e.require(label, [sys.executable, LAB / "src/actor.py", "--mode", mode,
                                       "--scenario", scenario, "--outdir", out], timeout=20)
                result = json.loads(raw)
                assert result == json.loads((out / "result.json").read_text(encoding="utf-8"))
                checked = verify(out)
                e.data["trials"].append({"round": round_id, "label": label, **checked})
        print(f"Round {round_id}: 16 actual actors verified", flush=True)
    totals = {mode: sum(t["executed_calls"] for t in e.data["trials"] if t["mode"] == mode) for mode in ("bad", "good")}
    assert totals == {"bad": 440, "good": 110}
except Exception as exc:
    failure = repr(exc)
    raise
finally:
    e.seal(failure)
