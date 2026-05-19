# RAG 工程化知识库问答项目

本项目是一个可运行的 RAG（检索增强生成）示例，包含以下能力：

- 前端提问与结果展示
- 后端检索与生成接口
- 文档索引（同步/异步）
- 问答与索引元数据持久化
- Docker Compose 一键启动

本文档按前端到后端的顺序说明：作用、操作方法、验证方式。

## 1. 系统总览（前端 -> 后端 -> Worker -> 存储）

### 1.1 前端（Vite）

作用：

- 提供问答页面与交互入口
- 调用后端 API，展示回答结果

### 1.2 后端（FastAPI）

作用：

- 接收前端问题
- 执行检索与生成主流程
- 产生日志、trace_id，并投递异步事件

### 1.3 Worker

作用：

- `persist_worker`：消费 `qa_turn` 事件，持久化 `conversations/messages`
- `vector_worker`：消费 `index_chunk` 事件，写入向量库并持久化 `documents/embeddings`

### 1.4 存储层

作用：

- Redis：短期上下文、检索快照、Stream 事件队列
- MySQL：长期业务数据（会话、消息、索引元数据）
- Chroma：向量存储与语义检索

## 2. 环境准备

### 2.1 基础要求

- Python 3.10+
- Node.js 18+
- Docker（可选，推荐）

### 2.2 安装依赖

```bash
pip install -r requirements.txt
```

前端依赖：

```bash
cd frontend
npm install
cd ..
```

## 3. 配置说明

### 3.1 环境变量

1. 复制示例配置：

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

2. 根据实际环境填写 `.env`。

注意：

- `.env` 不应提交到仓库
- `.env.example` 用于共享配置模板

### 3.2 MySQL 配置方式（二选一）

方式 A：单连接串

```text
DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/rag?charset=utf8mb4
```

方式 B：分项配置

```text
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=rag
MYSQL_CHARSET=utf8mb4
```

## 4. 启动方式（推荐 Docker）

### 4.1 一键启动

作用：

- 同时启动 `redis/mysql/backend/persist_worker/vector_worker/frontend`

操作：

```bash
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
```

停止服务：

```bash
docker compose down
```

停止并删除卷（会清空数据库与索引卷）：

```bash
docker compose down -v
```

### 4.2 访问地址

- 前端：`http://127.0.0.1:5173`
- 后端健康检查：`http://127.0.0.1:8000/api/health`

## 5. 本地开发启动（非 Docker）

按前端到后端依赖顺序建议如下。

### 5.1 启动前端

```bash
cd frontend
npm run dev
```

### 5.2 启动后端

```bash
uvicorn rag.main:app --reload --host 127.0.0.1 --port 8000
```

### 5.3 启动问答持久化 Worker

```bash
python -m rag.workers.persist_worker
```

### 5.4 启动向量 Worker

```bash
python -m rag.workers.vector_worker
```

## 6. 索引操作

统一索引入口：`rag.indexes.index_manager`

### 6.1 同步索引

作用：

- 直接写入 Chroma
- 同步写入 MySQL 元数据
- 完成后可立即检索

操作：

```bash
python -m rag.indexes.index_manager data/samples/基于CNN的论坛验证码识别实验.pptx
```

多文件：

```bash
python -m rag.indexes.index_manager data/samples/a.docx data/samples/b.pptx --continue-on-error
```

### 6.2 异步索引

作用：

- 先入队到 Redis Stream
- 再由 `vector_worker` 后台处理
- 适合大批量或慢索引场景

操作：

```bash
python -m rag.indexes.index_manager --async-index data/samples/基于CNN的论坛验证码识别实验.pptx
```

多文件：

```bash
python -m rag.indexes.index_manager --async-index data/samples/a.docx data/samples/b.pptx --continue-on-error
```

可选的 Stream 配置：

```text
REDIS_INDEX_EVENTS_STREAM=rag:index-events
REDIS_INDEX_EVENTS_GROUP=rag-index-workers
REDIS_INDEX_EVENTS_CONSUMER=index-consumer-1
```

## 7. 数据流与职责边界

### 7.1 问答链路

1. 前端发起问题
2. 后端读取短期上下文并执行向量检索
3. 生成回答并返回前端
4. 投递 `qa_turn` 事件
5. `persist_worker` 写入 `conversations/messages`

### 7.2 索引链路

- 同步模式：主流程直接写向量库 + 元数据
- 异步模式：先入 Stream，再由 `vector_worker` 写向量库 + 元数据

### 7.3 存储职责

- Redis：短期状态 + Stream 事件
- MySQL：长期业务存档
- Chroma：检索主库

说明：

- 当前默认不是 FAQ 缓存直出模式
- 仍是标准 RAG 流程（检索增强生成）

## 8. MySQL 数据表说明

索引与问答链路会使用四张核心表：

- `conversations`：会话级信息
- `messages`：问答消息
- `documents`：chunk 原文与文档元数据
- `embeddings`：向量元数据（`model`、`dimension` 等）

其中：

- `model` 写入真实 embedding 模型名
- `dimension` 写入实际向量维度

## 9. 数据库迁移（Alembic）

### 9.1 原则

- 生产环境仅通过 Alembic 管理 schema
- 不在应用启动时自动改表

### 9.2 常用命令

```powershell
# 升级到最新版本
alembic upgrade head

# 回滚一个版本
alembic downgrade -1
```

本地开发可用辅助脚本（仅开发环境）：

```powershell
python scripts/ensure_schema.py
```

## 10. CI 与代码质量

仓库已配置 GitHub Actions：`.github/workflows/ci.yml`

当前包含：

- `ruff`（风格与静态检查）
- `mypy`（类型检查）
- `pytest`（自动化测试）
- Alembic schema drift 检查

## 11. 常见问题

### 11.1 为什么文档入库后暂时检索不到？

如果使用异步索引，只有 `vector_worker` 消费完成后，文档才会在向量库中可检索。

### 11.2 Redis 的 `XACK` 是否会删除消息？

不会。`XACK` 只确认消费组状态，不删除 Stream 原始条目。

### 11.3 MySQL 是否是主检索库？

不是。主检索在向量库（Chroma）；MySQL 主要用于业务持久化与审计。

## 12. 最短可用命令清单

```bash
# 1) 启动后端
uvicorn rag.main:app --reload --host 127.0.0.1 --port 8000

# 2) 启动前端
cd frontend && npm run dev

# 3) 启动持久化 worker
python -m rag.workers.persist_worker

# 4) 启动向量 worker
python -m rag.workers.vector_worker

# 5) 同步建索引
python -m rag.indexes.index_manager data/samples/基于CNN的论坛验证码识别实验.pptx

# 6) 异步建索引
python -m rag.indexes.index_manager --async-index data/samples/基于CNN的论坛验证码识别实验.pptx
```
