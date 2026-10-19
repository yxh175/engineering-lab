import hashlib
import json
import re
def expected_data():
    return b''.join(f'{n+1}\t{n%10}\t{1700000000+(n*37)%1000}\tevent-{n+1:06}\n'.encode() for n in range(50000))
def query(tenant):
    assert tenant in [7,8]
    return f'SELECT id,tenant_id,created_at,payload FROM events WHERE tenant_id={tenant} ORDER BY created_at DESC,id DESC LIMIT 20'
def walk(x):
    if isinstance(x,dict):
        yield x
        for v in x.values():yield from walk(v)
    elif isinstance(x,list):
        for v in x:yield from walk(v)
def verify(case,tenant,plan_raw,tree_raw,rows_raw):
    normal=case=='ordered-control';assert tenant==(8 if normal else 7)
    expected=sorted([(n+1,n%10,1700000000+(n*37)%1000,f'event-{n+1:06}') for n in range(50000) if n%10==tenant],key=lambda r:(r[2],r[0]),reverse=True)[:20]
    actual=[]
    for line in rows_raw.decode().splitlines():
        p=line.split('\t');assert len(p)==4;actual.append((int(p[0]),int(p[1]),int(p[2]),p[3]))
    assert actual==expected
    plan=json.loads(plan_raw);tables=[x for x in walk(plan) if x.get('table_name')=='events'];assert len(tables)==1
    sorts=[x['using_filesort'] for x in walk(plan) if 'using_filesort' in x]
    is_sort=case=='sort';assert any(sorts) is is_sort
    nodes=[]
    for line in tree_raw.decode().splitlines():
        m=re.search(r'\(actual time=([\deE.+-]+)\.\.([\deE.+-]+) rows=([\deE.+-]+) loops=(\d+)\)',line)
        if m:nodes.append({'text':line.strip(),'rows':float(m[3]),'loops':int(m[4])})
    assert nodes and nodes[0]['rows']==20 and nodes[0]['loops']==1
    sorting=[n for n in nodes if '-> Sort:' in n['text']]
    assert bool(sorting) is is_sort
    access=[n for n in nodes if re.search(r'(?:scan|lookup) on events',n['text'],re.I)]
    assert len(access)==1 and access[0]['loops']==1
    if is_sort:
        children=[n for n in nodes if n['rows']==5000 and ('Filter:' in n['text'] or n in access)]
        assert children and access[0]['rows'] in [5000,50000]
        sort_input=5000
    else:
        assert tables[0]['key']=='ix_order' and access[0]['rows']==20 and 'ix_order' in access[0]['text']
        sort_input=0
    return {'case':case,'tenant':tenant,'returned_rows':20,'rows':actual,'using_filesort':is_sort,
            'access_type':tables[0]['access_type'],'key':tables[0].get('key'),'base_rows':access[0]['rows'],
            'base_node':access[0]['text'],'sort_input_rows':sort_input,'rows_sha256':hashlib.sha256(rows_raw).hexdigest(),'passed':True}
