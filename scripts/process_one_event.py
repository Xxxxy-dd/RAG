from redis import Redis
import os
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))
from rag.workers.vector_worker import VectorWorker

r = Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
stream = os.getenv("REDIS_INDEX_EVENTS_STREAM", "rag:index-events")
items = r.xrange(stream, min="-", max="+", count=1)
print("items", len(items))
if not items:
    print("no items")
    sys.exit(0)
msg_id, fields = items[0]
print("msg id", msg_id)
worker = VectorWorker()
vec = worker._load_vector_store()
print("vector store", type(vec))
payload = worker._parse_fields(fields)
print("payload keys", payload.keys())
from langchain_core.documents import Document

chunk_text = payload.get("chunk_text")
chunk_metadata = payload.get("chunk_metadata")
doc = Document(page_content=chunk_text, metadata=chunk_metadata)
from rag.storage import make_document_key, make_vector_id

doc_key = make_document_key(doc, payload["collection_name"])
vid = make_vector_id(doc_key)
doc.metadata = {
    **dict(doc.metadata or {}),
    "collection_name": payload["collection_name"],
    "document_key": doc_key,
    "vector_id": vid,
}
print("upsert...")
try:
    worker._upsert_vector(vec, doc, vid)
    print("upsert ok")
except Exception as e:
    print("upsert exc", e)
print("persist to mysql...")
try:
    worker._persist_to_mysql(doc, vid, payload.get("embedding_model"))
    print("persist ok")
except Exception as e:
    print("persist exc", e)
print("ack...")
ack = r.xack(stream, os.getenv("REDIS_INDEX_EVENTS_GROUP", "rag-index-workers"), msg_id)
print("ack ret", ack)
