import json
from pathlib import Path
def snapshot(path):
    rows=json.loads(Path(path).read_bytes());assert len(rows)==10000
    for n,row in enumerate(rows,1):
        assert row=={'id':n,'category':int(n%100==0),'embedding':f'[{n},0]'}
    return rows
def walk(plan):
    yield plan
    for p in plan.get('Plans',[]):yield from walk(p)
def verify(case,raw):
    lines=raw.decode().splitlines();report=json.loads(lines[0]);plan=json.loads('\n'.join(lines[1:]))[0]
    assert report['case']==case and report['ef_search']=='40' and report['max_scan_tuples']=='20000' and report['scan_mem_multiplier']=='1'
    assert report['iterative_scan']==('strict_order' if case=='iterative-filtered' else 'off')
    rows=report['rows'];assert 0<=len(rows)<=10 and len({r['id'] for r in rows})==len(rows)
    filtered=case!='unfiltered-control'
    for r in rows:
        assert 1<=r['id']<=10000 and r['category']==int(r['id']%100==0) and r['distance']==r['id']
        if filtered:assert r['category']==1
    assert [r['distance'] for r in rows]==sorted(r['distance'] for r in rows)
    expected=list(range(100,1001,100)) if filtered else list(range(1,11))
    nodes=list(walk(plan['Plan']));top=plan['Plan'];assert top['Node Type']=='Limit' and top['Actual Rows']==len(rows) and top['Actual Loops']==1
    if case=='exact-filtered':
        assert [r['id'] for r in rows]==expected
        scans=[p for p in nodes if p['Node Type']=='Seq Scan'];assert len(scans)==1 and scans[0]['Actual Rows']==100 and scans[0]['Rows Removed by Filter']==9900
        assert not any(p['Node Type']=='Index Scan' for p in nodes)
    else:
        scans=[p for p in nodes if p['Node Type']=='Index Scan'];assert len(scans)==1 and scans[0]['Index Name']=='ix_embedding'
        assert scans[0]['Actual Loops']==1 and scans[0]['Actual Rows']==len(rows)
        if filtered:assert scans[0]['Rows Removed by Filter']>0 and 'category' in scans[0]['Filter']
        else:assert [r['id'] for r in rows]==expected
    scan=scans[0]
    return {'case':case,'backend_pid':report['backend_pid'],'rows':len(rows),'ids':[r['id'] for r in rows],
            'exact_top10_recall':len(set(r['id'] for r in rows)&set(expected))/10,
            'scan_node':scan['Node Type'],'scan_rows':scan['Actual Rows'],'rows_removed_by_filter':scan.get('Rows Removed by Filter',0),
            'execution_ms':plan['Execution Time'],'passed':True}
