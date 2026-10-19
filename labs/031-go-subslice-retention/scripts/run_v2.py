from pathlib import Path
import hashlib
import json
import os
import sys

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parents[1]
sys.path[:0] = [str(ROOT / "shared/scripts"), str(LAB / "src")]
from evidence import Evidence
from verify_v2 import verify

GO = os.environ.get("LAB031_GO", "go")
EXE = LAB / ".work/lab031.exe"
EXE.parent.mkdir(exist_ok=True)
e = Evidence(LAB, "native-go-memory", [LAB/n for n in ["go.mod", "src/main.go", "src/verify_v2.py", "scripts/run_v2.py"]],
    {"cases": ["subslice", "cap-limited", "copied"], "rounds": 10, "array_bytes": 32 << 20,
     "kept_bytes": 32, "gc_cycles_per_stage": 2, "gomaxprocs": 1, "mem_profile_rate": 1})
failure = None
try:
    version = e.require("go-version", [GO, "version"]).decode()
    assert "go1.25.4 windows/amd64" in version
    e.require("go-env", [GO, "env", "-json", "GOOS", "GOARCH", "GOVERSION", "CGO_ENABLED", "GOTOOLCHAIN"])
    e.require("build", [GO, "build", "-trimpath", "-o", EXE, "./src"], timeout=60)
    e.require("vet", [GO, "vet", "./src"], timeout=60)
    for name in ["bytes.Clone", "runtime.MemStats", "runtime.MemProfile", "runtime.KeepAlive"]:
        e.require("doc-"+name.replace(".", "-"), [GO, "doc", name])
    (e.dest/"binary.json").write_text(json.dumps({"sha256": hashlib.sha256(EXE.read_bytes()).hexdigest(), "size": EXE.stat().st_size})+"\n", encoding="utf-8", newline="\n")
    (e.dest/"actors").mkdir()
    for round_id in range(1,11):
        for mode in e.data["parameters"]["cases"]:
            label = f"{mode}-{round_id:02}"
            out = e.dest/"actors"/label
            raw = e.require(label, [EXE, "-case", mode, "-outdir", out], timeout=15)
            result = json.loads(raw)
            assert result == json.loads((out/"result.json").read_bytes())
            profiles = {}
            for stage in ["baseline", "held", "released"]:
                profiles[stage] = e.require(label+"-"+stage+"-profile", [GO, "tool", "pprof", "-raw", out/(stage+".pprof")]).decode()
            e.data["trials"].append({"round": round_id, "label": label, **verify(result, profiles)})
        print(f"Round {round_id}: payload, live heap and original pprof verified", flush=True)
except Exception as exc:
    failure = repr(exc)
    raise
finally:
    e.seal(failure)
