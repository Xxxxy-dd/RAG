from redis import Redis
import os

r = Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
stream = os.getenv("REDIS_INDEX_EVENTS_STREAM", "rag:index-events")
print("stream:", stream)
try:
    info = r.xinfo_groups(stream)
    print("groups:")
    for g in info:
        print(g)
except Exception as e:
    print("xinfo_groups error", e)

try:
    consumers = r.xinfo_consumers(
        stream, os.getenv("REDIS_INDEX_EVENTS_GROUP", "rag-index-workers")
    )
    print("consumers:")
    for c in consumers:
        print(c)
except Exception as e:
    print("xinfo_consumers error", e)

print("pending entries:")
try:
    pending = r.xpending(stream, os.getenv("REDIS_INDEX_EVENTS_GROUP", "rag-index-workers"))
    print(pending)
except Exception as e:
    print("xpending error", e)

items = r.xrange(stream, min="-", max="+", count=10)
print("first 10 items:")
for id, f in items:
    print(id)
