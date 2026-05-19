# RAG Frontend

React + Vite + TypeScript + Ant Design 前端，默认通过 `/api/qa` 与后端通信。

## 启动

```bash
cd frontend
npm install
npm run dev
```

## 说明

- 开发环境默认将 `/api` 代理到 `http://127.0.0.1:8000`
- 需要后端 FastAPI 服务先运行
- 可用 `VITE_API_BASE_URL` 自定义 API 地址
