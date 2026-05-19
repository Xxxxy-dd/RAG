from pathlib import Path
import sys
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from redis import Redis
import os
from rag.workers.vector_worker import VectorWorker

r = Redis.from_url(os.getenv('REDIS_URL','redis://127.0.0.1:6379/0'))
stream=os.getenv('REDIS_INDEX_EVENTS_STREAM','rag:index-events')
items = r.xrange(stream, min='-', max='+')
print('found', len(items))
worker = VectorWorker()
for msg_id, fields in items[:3]:
    print('MSG ID', msg_id)
    print('raw keys types:')
    for k in fields.keys():
        print(' -', repr(k), type(k))
    print('raw values types:')
    for v in fields.values():
        print(' -', repr(v)[:120], type(v))
    payload = worker._parse_fields(fields)
    print('payload keys:', payload.keys())
    print('event_type:', payload.get('event_type'))
    print('chunk_text len:', len(payload.get('chunk_text','')))
    print('---')
