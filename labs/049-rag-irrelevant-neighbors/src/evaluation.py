import numpy as np
def confusion(rows,threshold):
    accepted=[r['top1_score']>=threshold for r in rows]
    return {'tp':sum(a and r['answerable'] for a,r in zip(accepted,rows)),
            'fp':sum(a and not r['answerable'] for a,r in zip(accepted,rows)),
            'tn':sum(not a and not r['answerable'] for a,r in zip(accepted,rows)),
            'fn':sum(not a and r['answerable'] for a,r in zip(accepted,rows))}
def calibrate(rows):
    scores=sorted(set(r['top1_score'] for r in rows))
    candidates=[-1.000001]+[(x+y)/2 for x,y in zip(scores,scores[1:])]+[1.000001]
    positive=sum(r['answerable'] for r in rows);negative=len(rows)-positive;assert positive and negative
    table=[]
    for threshold in candidates:
        c=confusion(rows,threshold);table.append({'threshold':threshold,**c,'balanced_accuracy':(c['tp']/positive+c['tn']/negative)/2})
    best=max(table,key=lambda x:(x['balanced_accuracy'],x['threshold']))
    return best['threshold'],table
def rankings(fixture,scores):
    docs=fixture['docs'];qs=fixture['queries'];assert scores.shape==(len(qs),len(docs))
    rows=[]
    for q,s in zip(qs,scores):
        order=sorted(range(len(docs)),key=lambda j:(-float(s[j]),docs[j]['id']))
        top=[docs[j]['id'] for j in order[:3]]
        rows.append({'query_id':q['id'],'split':q['split'],'answerable':q['answerable'],'top1_score':float(s[order[0]]),'top3':top,
                     'relevant_in_top3':bool(set(q['relevant'])&set(top)),'ranking':[{'doc':docs[j]['id'],'score':float(s[j])} for j in order]})
    return rows
def evaluate(fixture,scores):
    rows=rankings(fixture,scores);cal=[r for r in rows if r['split']=='calibration'];test=[r for r in rows if r['split']=='test']
    threshold,table=calibrate(cal)
    policies=[]
    for case,cut in [('always-top3',-1.000001),('calibrated-gate',threshold)]:
        c=confusion(test,cut)
        policies.append({'case':case,'threshold':cut,**c,'accepted':c['tp']+c['fp'],'coverage':(c['tp']+c['fp'])/len(test),
                         'relevant_at3':sum(r['answerable'] and r['relevant_in_top3'] for r in test),
                         'accepted_without_relevant':sum(r['top1_score']>=cut and not r['relevant_in_top3'] for r in test),'test_queries':len(test)})
    return {'calibrated_threshold':threshold,'calibration_table':table,'per_query':rows,'policies':policies}
