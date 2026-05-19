import sys
from pathlib import Path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from rag.memory.redis_memory import read_index_chunk_events

print('project_root:', project_root)
batches = read_index_chunk_events(count=50, block_ms=2000)
print('batches len:', len(batches))
for stream_key, messages in batches:
    print('stream:', stream_key)
    for mid, fields in messages:
        print('  ', mid, fields)
