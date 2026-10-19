"""Check evidence bytes and explicit pass/failure expectations separately."""
import argparse
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifests',nargs='+',type=Path)
    parser.add_argument('--expect-failed',action='store_true',help='Require all_passed=false; only integrity can pass')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();records=[]
    for input_path in args.manifests:
        p=input_path.resolve();folder=p.parent;lab=folder.parents[1]
        assert lab.is_relative_to(ROOT/'labs') and folder.parent.name=='results'
        d=json.loads(p.read_text(encoding='utf-8'))
        assert d['all_passed'] is (not args.expect_failed)
        assert bool(d['failure']) is args.expect_failed
        assert d['trials'] and all(t['passed'] for t in d['trials']) is (not args.expect_failed)
        for name,value in d['source_sha256'].items():assert sha(lab/name)==value,(p,name)
        for name,value in d['shared_source_sha256'].items():assert sha(ROOT/name)==value,(p,name)
        for name,value in d['artifact_sha256'].items():assert sha(folder/name)==value,(p,name)
        records.append({'manifest':p.relative_to(ROOT).as_posix(),'manifest_sha256':sha(p),'integrity_passed':True,
                        'experiment_passed':d['all_passed'],'expected_experiment_passed':not args.expect_failed,
                        'failure':d['failure'],'artifact_count':len(d['artifact_sha256']),
                        'lab_source_count':len(d['source_sha256']),'shared_source_count':len(d['shared_source_sha256'])})
        print(f'{folder.name}: integrity PASS; experiment {"failed (as recorded)" if args.expect_failed else "passed"}')
    report={'checked_utc':datetime.now(timezone.utc).isoformat(),'integrity_passed':True,
            'expect_failed_experiments':args.expect_failed,'records':records,'audit_script_sha256':sha(Path(__file__))}
    if args.output:
        assert not args.output.exists()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n')

if __name__=='__main__':main()
