import json

class CacheAside:
    """Serial demo: distinguish absent cache, negative entry and empty real value."""
    def __init__(self,redis,origin,negative_cache,negative_ttl_ms):
        self.redis=redis;self.origin=origin
        self.negative_cache=negative_cache;self.negative_ttl_ms=negative_ttl_ms
        self.origin_calls=0

    def lookup(self,label,item_id):
        key=f'lab016:item:{item_id}'
        cached=self.redis.call(label+'-get','GET',key)
        if cached is not None:
            entry=json.loads(cached)
            return {'id':item_id,'value':entry.get('value'),'state':'VALUE_HIT' if entry['found'] else 'NEGATIVE_HIT','origin_label':None}
        query=f'SELECT HEX(payload) FROM items WHERE id={int(item_id)};'
        output=self.origin.execute(label+'-origin',query)
        self.origin_calls+=1
        lines=output.splitlines();assert len(lines)<=1
        found=bool(lines)
        value=bytes.fromhex(lines[0].decode()).decode() if found else None
        if found or self.negative_cache:
            entry={'found':found}
            if found:entry['value']=value
            ttl=60000 if found else self.negative_ttl_ms
            assert self.redis.call(label+'-set','SET',key,json.dumps(entry,separators=(',',':')),'PX',ttl)==b'OK'
        return {'id':item_id,'value':value,'state':'MISS','origin_label':label+'-origin'}
