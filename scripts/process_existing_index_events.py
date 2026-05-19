from pathlib import Path
import sys
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from redis import Redis
import os
import json
from rag.workers.vector_worker import VectorWorker
from langchain_core.documents import Document
from rag.storage import make_document_key, make_vector_id

REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
STREAM_KEY = os.getenv('REDIS_INDEX_EVENTS_STREAM', 'rag:index-events')
GROUP_NAME = os.getenv('REDIS_INDEX_EVENTS_GROUP', 'rag-index-workers')

r = Redis.from_url(REDIS_URL)
worker = VectorWorker()
vector_store = worker._load_vector_store()

items = r.xrange(STREAM_KEY, min='-', max='+')
print('found', len(items), 'items')
processed = 0
for msg_id, fields in items:
    try:
        payload = worker._parse_fields(fields)
        if payload.get('event_type') != 'index_chunk':
            # ack non-index events to avoid reprocessing
            r.xack(STREAM_KEY, GROUP_NAME, msg_id)
            continue
        chunk_text = payload.get('chunk_text') or ''
        if not chunk_text:
            r.xack(STREAM_KEY, GROUP_NAME, msg_id)
            continue
        chunk_metadata = dict(payload.get('chunk_metadata') or {})
        document = Document(page_content=chunk_text, metadata=chunk_metadata)
        document_key = make_document_key(document, payload['collection_name'])
        vector_id = make_vector_id(document_key)
        document.metadata = {**dict(document.metadata or {}), 'collection_name': payload['collection_name'], 'document_key': document_key, 'vector_id': vector_id}

        # upsert
        try:
            worker._upsert_vector(vector_store, document, vector_id)
            worker._persist_to_mysql(document, vector_id, payload.get('embedding_model'))
            r.xack(STREAM_KEY, GROUP_NAME, msg_id)
            processed += 1
            if processed % 20 == 0:
                print('processed', processed)
        except Exception as e:
            print('failed to process', msg_id, e)
    except Exception as e:
        print('parse error', msg_id, e)

print('done, processed', processed)
