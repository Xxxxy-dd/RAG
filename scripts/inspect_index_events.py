from redis import Redis
import os
r=Redis.from_url(os.getenv('REDIS_URL','redis://127.0.0.1:6379/0'))
key=os.getenv('REDIS_INDEX_EVENTS_STREAM','rag:index-events')
items=r.xrange(key, min='-', max='+')
print('total', len(items))
for i,(id,fields) in enumerate(items[-50:], start=1):
    decoded={}
    for k,v in fields.items():
        dk = k.decode() if isinstance(k,bytes) else k
        dv = v.decode() if isinstance(v,bytes) else v
        decoded[dk]=dv
    print(i, id, decoded)
