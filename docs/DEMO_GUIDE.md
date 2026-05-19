# Demo Guide

This guide helps you present the project in an interview or portfolio review.

## 1. Start The Stack

```powershell
docker compose up -d --build
```

For local frontend development:

```powershell
cd frontend
npm run dev -- --host 127.0.0.1 --port 5174
```

## 2. Index A Sample Document

Sample files are available under `data/samples`.

```powershell
python -m rag.indexes.index_manager "data/samples/基于CNN的论坛验证码识别实验报告.docx"
```

Async indexing path:

```powershell
python -m rag.indexes.index_manager --async-index "data/samples/基于CNN的论坛验证码识别实验报告.docx"
python -m rag.workers.vector_worker
```

## 3. Ask Demo Questions

Use questions that prove the system is reading the indexed document:

- 这份实验报告主要研究了什么？
- 系统识别验证码的大致流程是什么？
- 文档里提到了哪些模型、工具或实验步骤？
- 可以把实验结论总结成三点吗？

## 4. Show User-Facing Features

- Start a new conversation.
- Ask a follow-up question.
- Show persisted history.
- Export the conversation as Markdown or JSON.
- Open the reference content section to show answer traceability.

## 5. Explain Engineering Choices

- Chroma is used for vector retrieval.
- Redis stores short-term context and stream events.
- MySQL stores durable conversations, messages, documents, and embedding metadata.
- Redis Streams keep indexing and persistence work out of the request path.
- Worker retries, idempotency keys, dead-letter streams, and trace IDs improve reliability.

## 6. Suggested 60-Second Pitch

我做的是一个企业知识库 RAG 问答系统。用户可以把文档索引进知识库，然后在前端直接提问，系统会检索相关片段、进行重排和问答，并返回可追溯的参考内容。后端用 FastAPI，向量库用 Chroma，Redis 负责会话缓存和异步事件流，MySQL 持久化会话、消息和文档元数据。为了让项目更像真实应用，我还做了 Redis Streams worker、幂等和重试、Docker Compose、测试、lint 和 CI。
