from pathlib import Path
import sys

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from rag.workers.vector_worker import VectorWorker
from rag.memory.redis_memory import read_index_chunk_events
from redis import Redis
import os

r = Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
stream = os.getenv("REDIS_INDEX_EVENTS_STREAM", "rag:index-events")

items = r.xrange(stream, min="-", max="+")
print("XRANGE count", len(items))
worker = VectorWorker()
for msg_id, fields in items:
    payload = worker._parse_fields(fields)
    print(
        msg_id,
        "event_type=",
        payload.get("event_type"),
        "len_text=",
        len(payload.get("chunk_text", "")),
    )

print("Now testing read_index_chunk_events")
batches = read_index_chunk_events(count=20, block_ms=1000)
print("batches:", batches)
