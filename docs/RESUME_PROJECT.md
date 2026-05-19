# Resume Project Notes

## 中文简历版本

**企业知识库 RAG 问答系统**  
独立开发一个面向企业文档问答的 RAG 应用，基于 FastAPI、React、Chroma、Redis、MySQL 实现文档解析、向量索引、语义检索、查询改写、重排问答、会话记忆与参考内容追溯；支持异步索引任务、历史会话管理、Markdown/JSON 导出，并使用 Docker Compose、CI、pytest 和 Ruff 完成基础工程化建设。

### 可拆成项目要点

- 设计并实现完整 RAG 问答链路：文档加载、切分、向量索引、语义检索、重排、Prompt 组装与回答生成。
- 使用 Redis 保存短期会话上下文，并通过 Redis Streams 解耦问答持久化和异步向量索引任务。
- 使用 MySQL 持久化会话、消息、文档与 embedding 元数据，并通过 Alembic 管理数据库迁移。
- 为后台 worker 增加幂等键、重试计数、死信队列和 trace_id 追踪，提升任务处理可靠性。
- 使用 React + Ant Design 构建面向用户的知识问答界面，支持历史会话、清空会话、参考内容展示和会话导出。
- 使用 Docker Compose 编排后端、前端、Redis、MySQL、worker 等服务，并配置 pytest、Ruff、Mypy、GitHub Actions 质量检查。

## English Resume Version

**Enterprise Knowledge Base RAG QA System**  
Built a full-stack Retrieval-Augmented Generation application with FastAPI, React, Chroma, Redis, and MySQL. Implemented document parsing, vector indexing, semantic retrieval, query rewriting, reranking, session memory, traceable reference context, asynchronous indexing workers, persistent chat history, Markdown/JSON export, Docker Compose orchestration, and CI quality checks.

## Interview Talking Points

- Why the system separates vector retrieval, short-term memory, and durable storage.
- Why Redis Streams are used instead of writing everything synchronously during API requests.
- How idempotency keys prevent duplicate worker writes during retries.
- How trace IDs connect API logs, stream events, worker processing, and database records.
- What tradeoffs were made because this is a portfolio project rather than a production SaaS product.
