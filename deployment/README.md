# Deployment Guide

This project now has a three-layer persistence flow:

- Redis: short-term session cache and Redis Streams for reliable events
- MySQL: long-term conversation, message, document, and embedding metadata storage
- Vector DB: Chroma index for semantic retrieval

## Recommended local startup order

1. Start Redis.
2. Start MySQL.
3. Configure environment variables.
4. Start the FastAPI backend.
5. Start the frontend.
6. Start background workers.

## Environment variables

```text
REDIS_URL=redis://127.0.0.1:6379/0
REDIS_EVENTS_STREAM=rag:events
REDIS_EVENTS_GROUP=rag-persist-workers
REDIS_EVENTS_CONSUMER=consumer-1
REDIS_INDEX_EVENTS_STREAM=rag:index-events
REDIS_INDEX_EVENTS_GROUP=rag-index-workers
REDIS_INDEX_EVENTS_CONSUMER=index-consumer-1
DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/rag?charset=utf8mb4
LLM_API_KEY=...
EMBEDDINGS_API_KEY=...
```

If you prefer explicit MySQL fields instead of `DATABASE_URL`, use `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`, and `MYSQL_CHARSET`.

## Commands

Backend:

```powershell
cd "E:\VS code\RAG"
uvicorn rag.main:app --reload --host 127.0.0.1 --port 8000
```

One-click local startup:

```powershell
cd "E:\VS code\RAG"
start_all.bat
```

Frontend:

```powershell
cd "E:\VS code\RAG\frontend"
npm run dev
```

Persist worker:

```powershell
cd "E:\VS code\RAG"
python -m rag.workers.persist_worker --once
```

Vector worker:

```powershell
cd "E:\VS code\RAG"
python -m rag.workers.vector_worker --once
```

Async document enqueue:

```powershell
cd "E:\VS code\RAG"
python -m rag.indexes.index_manager --async-index data/samples/基于CNN的论坛验证码识别实验.pptx
```

Sync index build:

```powershell
cd "E:\VS code\RAG"
python -m rag.indexes.index_manager data/samples/基于CNN的论坛验证码识别实验.pptx
```

## Validation checklist

- `GET /api/health` returns `{"status": "ok"}`.
- Submitting a question creates Redis session keys and a Redis Stream event.
- `rag.workers.persist_worker` writes the turn to MySQL.
- `rag.workers.vector_worker` upserts chunks into Chroma and mirrors metadata to MySQL.
- `GET /api/session/{session_id}/messages` returns persisted MySQL messages.

## Backup notes

- Redis: enable RDB or AOF depending on your retention needs.
- MySQL: schedule periodic logical backups of the `rag` database.
- Chroma: back up the persist directory under `rag/indexes/chroma_db` or your custom `persist_directory`.

## Monitoring notes

- Watch backend logs for Redis connection failures and MySQL warnings.
- Keep the two workers running as separate processes or services.
- Alert on worker lag if Redis Stream pending entries start to grow.
