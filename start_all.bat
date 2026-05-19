@echo off
chcp 65001 >nul
title RAG All Services

cd /d "%~dp0"

echo [1/3] 启动 FastAPI 后端...
start "RAG Backend" cmd /k "cd /d ""%~dp0"" && uvicorn rag.main:app --reload --host 127.0.0.1 --port 8000"

echo [2/3] 启动持久化 worker...
start "RAG Persist Worker" cmd /k "cd /d ""%~dp0"" && python -m rag.workers.persist_worker"

echo [3/3] 启动向量 worker...
start "RAG Vector Worker" cmd /k "cd /d ""%~dp0"" && python -m rag.workers.vector_worker"

echo.
echo 已启动三个窗口：后端、persist worker、vector worker。
echo 如果你的 Python 环境需要先激活 conda，请先在当前终端激活对应环境再运行此脚本。
pause