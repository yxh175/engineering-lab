import hashlib
import json
import re

def expected_data():
    codes=['1','01','1x',' 1','1.0']
    return b''.join(f'{n+1}\t{(codes[n] if n<5 else str(n+1000)).encode().hex().upper()}\n'.encode() for n in range(50000))

def tables(x):
    found=[]
    if isinstance(x,dict):
        if 'table_name' in x:found.append(x)
        for v in x.values():found+=tables(v)
    elif isinstance(x,list):
        for v in x:found+=tables(v)
    return found

def verify(case,plan_raw,tree_raw,rows_raw):
    lines=rows_raw.decode().splitlines();rows=[];warnings=[]
    for line in lines:
        parts=line.split('\t')
        if parts[0]=='Warning':
            assert len(parts)==3;warnings.append((int(parts[1]),parts[2]))
        else:
            assert len(parts)==2;rows.append((int(parts[0]),bytes.fromhex(parts[1]).decode()))
    expected={'numeric':[(1,'1'),(2,'01'),(3,'1x'),(4,' 1'),(5,'1.0')],'string':[(1,'1')],'string-control':[(6,'1005')]}
    assert rows==expected[case]
    if case=='numeric':assert warnings and all(w[0]==1292 and '1x' in w[1] for w in warnings)
    else:assert not warnings
    plan=json.loads(plan_raw);nodes=tables(plan);assert len(nodes)==1 and nodes[0]['table_name']=='fixture'
    access=nodes[0]['access_type'];key=nodes[0].get('key')
    if case=='numeric':assert access in {'ALL','index'}
    else:assert access=='ref' and key=='ix_code'
    actual=[]
    for line in tree_raw.decode().splitlines():
        m=re.search(r'\(actual time=([\deE.+-]+)\.\.([\deE.+-]+) rows=([\deE.+-]+) loops=(\d+)\)',line)
        if m:actual.append({'text':line.strip(),'rows':float(m[3]),'loops':int(m[4])})
    assert actual and actual[0]['rows']==len(rows) and actual[0]['loops']==1
    leaf=[n for n in actual if ('scan on fixture' in n['text'].lower() or 'lookup on fixture' in n['text'].lower())]
    assert len(leaf)==1 and leaf[0]['loops']==1
    read=50000 if case=='numeric' else 1
    assert leaf[0]['rows']==read
    return {'case':case,'returned_rows':len(rows),'rows':rows,'warnings':warnings,
            'access_type':access,'key':key,'base_rows':read,'base_node':leaf[0]['text'],
            'rows_sha256':hashlib.sha256(rows_raw).hexdigest(),'passed':True}
