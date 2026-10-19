import csv
import json
import re
import shutil
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parents[1]
sys.path.insert(0, str(ROOT / "shared/scripts"))
from evidence import Evidence, sha

IMAGE = "golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb"
CASES = [("inside", 4), ("outside", 4), ("inside", 16), ("outside", 16)]


def profile_stats(raw, function):
    text = raw.decode()
    sample_text = text.split("Samples:", 1)[1].split("Locations", 1)[0]
    samples = []
    for line in sample_text.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+):\s*([\d ]+)", line)
        if m:
            samples.append((int(m[1]), int(m[2]), m[3].split()))
    locations, current = {}, None
    for line in text.split("Locations", 1)[1].split("Mappings", 1)[0].splitlines():
        m = re.match(r"\s*(\d+):", line)
        if m:
            current = m[1]
        if current:
            locations[current] = locations.get(current, "") + line
    selected = [s for s in samples if any(function in locations.get(i, "") for i in s[2])]
    return {"total_delay_ns": sum(x[1] for x in samples), "function_delay_ns": sum(x[1] for x in selected),
            "function_contentions": sum(x[0] for x in selected)}


def verify(d, code, mode, workers):
    assert code == 0 and d["case"] == mode and d["workers"] == workers
    assert d["go_version"] == "go1.25.4" and d["goos"] == "linux" and d["goarch"] == "amd64" and d["gomaxprocs"] == 1
    assert d["total"] == d["completed"] == len(d["operations"]) == 128 and d["sum"] == sum(range(1,129))
    assert d["delay_ns"] == 4000000 and [op["id"] for op in d["operations"]] == list(range(1,129))
    assert sorted(op["worker"] for op in d["operations"]) == sorted(list(range(workers))*(128//workers))
    for op in d["operations"]:
        assert op["latency_ns"] >= 4000000 and op["wait_ns"] >= 0 and op["hold_ns"] >= 0
        assert op["latency_ns"] >= op["wait_ns"] + op["hold_ns"]
        if mode == "inside":
            assert op["hold_ns"] >= 4000000
    delta = sum(d['cpu_after'].values()) - sum(d['cpu_before'].values())
    assert delta == d['cpu_time_us'] >= 0
    assert abs(d['cpu_one_core_percent'] - delta*100000/d['wall_ns']) < 1e-8
    if mode == "inside":
        assert d["wall_ns"] >= 128*4000000 and d["cpu_one_core_percent"] < 30


def run():
    sources = [LAB/"go.mod",LAB/"docker-compose.yml",LAB/"src/main.go",LAB/"src/service.go",Path(__file__)]
    e = Evidence(LAB,"docker",sources,{"cases":CASES,"repeats_per_case":10,"total":128,"delay_ms":4,
                 "gomaxprocs":1,"cpu_limit":1,"memory_limit":"512MiB","mutex_fraction":1,"block_rate":1,
                 "timing":"closed-loop; worker creation before window; profiles/JSON after window",
                 "order":"case list forward on odd repeats, reversed on even repeats","cpu_method":"getrusage RUSAGE_SELF user+system us delta / wall ns, one-core percent"})
    compose = ["docker","compose","-p","engineering-lab-011","-f",str(LAB/"docker-compose.yml")]
    work=LAB/".work/linux"
    work.mkdir(parents=True,exist_ok=True)
    cid,failure=None,None
    try:
        e.require("docker-version",["docker","version"])
        e.require("compose-version",["docker","compose","version"])
        e.require("image-inspect",["docker","image","inspect",IMAGE])
        e.require("startup",compose+["up","-d","--wait"],timeout=120)
        cid=e.require("container-id",compose+["ps","-q","builder"]).decode().strip()
        assert re.fullmatch(r"[a-f0-9]{64}",cid)
        e.require("container-inspect",["docker","inspect",cid])
        e.require("cgroup-parameters",["docker","exec",cid,"cat","/sys/fs/cgroup/cpu.max","/sys/fs/cgroup/memory.max"])
        base=["docker","exec",cid]
        assert b"go1.25.4" in e.require("go-version",base+["go","version"])
        e.require("go-env",base+["go","env","-json","GOVERSION","GOOS","GOARCH","CGO_ENABLED","GOMAXPROCS","GOGC"])
        e.require("go-vet",base+["go","vet","./src"],timeout=180)
        e.require("go-build",base+["go","build","-o","/out/mutex-demo","./src"],timeout=180)
        e.data["executable_sha256"]=sha(work/"mutex-demo")
        for repeat in range(1,11):
            for mode,workers in (CASES if repeat%2 else list(reversed(CASES))):
                label=f"{mode}-{workers}-{repeat:02d}"
                record,out,err=e.run(label,base+["/out/mutex-demo","-case",mode,"-workers",str(workers),"-out",f"/out/trials/{label}"],timeout=15)
                d,metrics,error={}, {}, ""
                try:
                    d=json.loads(out)
                    verify(d,record["exit_code"],mode,workers)
                    for name in ["mutex","block"]:
                        for suffix in ["pprof","txt"]:
                            shutil.copyfile(work/f"trials/{label}/{name}.{suffix}",e.dest/label/f"{name}.{suffix}")
                        profile=f"/out/trials/{label}/{name}.pprof"
                        raw=e.require(f"{label}-{name}-raw",base+["go","tool","pprof","-raw","/out/mutex-demo",profile])
                        e.require(f"{label}-{name}-top",base+["go","tool","pprof","-top","-cum","-unit=ms","-nodefraction=0","-nodecount=25","-sample_index=delay","/out/mutex-demo",profile])
                        function="main.(*service).lockedDelay" if mode=="inside" else "main.(*service).outsideDelay"
                        metrics[name]=profile_stats(raw,function)
                    if mode=="inside":
                        assert metrics['mutex']['function_contentions']>0 and metrics['mutex']['function_delay_ns']>d['wall_ns']
                        assert metrics['block']['function_contentions']>0 and metrics['block']['function_delay_ns']>0
                except (AssertionError,ValueError,KeyError,IndexError,FileNotFoundError) as exc:
                    error=str(exc) or type(exc).__name__
                e.data['trials'].append({'case':mode,'workers':workers,'trial':repeat,'passed':not error,
                                         'verification_error':error,'process_exit':record['exit_code'],
                                         'profile_metrics':metrics,**d})
                print(f"{label}: {'FAIL' if error else 'PASS'} wall_ms={d.get('wall_ns',0)/1e6:.3f} CPU={d.get('cpu_one_core_percent',0):.3f}% {error}",flush=True)
        comparisons=[]
        for workers in [4,16]:
            for repeat in range(1,11):
                pair={t['case']:t for t in e.data['trials'] if t['workers']==workers and t['trial']==repeat}
                ratio=pair['inside']['wall_ns']/pair['outside']['wall_ns']
                comparisons.append({'workers':workers,'trial':repeat,'bad_good_wall_ratio':ratio,'passed':ratio>2})
        e.data['paired_comparisons']=comparisons
        if not all(x['passed'] for x in comparisons):
            failure='same-concurrency good does not meet preregistered half-wall criterion'
        e.require("shutdown",compose+["down","--remove-orphans"],timeout=60)
    except Exception as exc:
        failure=str(exc) or type(exc).__name__
        print(failure,file=sys.stderr)
        if cid:
            e.run("failure-shutdown",compose+["down","--remove-orphans"],timeout=60)
    if len(e.data['trials'])!=40:
        failure=failure or 'incomplete 40-process matrix'
    fields=['case','workers','trial','passed','process_exit','wall_ns','cpu_time_us','cpu_one_core_percent','completed','sum']
    with (e.dest/'summary.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        w.writerows({k:t.get(k,'') for k in fields} for t in e.data['trials'])
    return e.seal(failure)


if __name__=='__main__':
    raise SystemExit(0 if run() else 1)
