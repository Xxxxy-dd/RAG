# Project Highlights

This file is a quick reviewer-facing summary for resumes, interviews, and repository browsing.

## What This Project Demonstrates

- Built a complete RAG QA application with FastAPI, React, Chroma, Redis, and MySQL.
- Designed asynchronous persistence and indexing workers with Redis Streams consumer groups.
- Added idempotency, retry tracking, dead-letter queues, and trace propagation for worker reliability.
- Persisted conversation history, document metadata, and embedding metadata in MySQL with Alembic migrations.
- Containerized the full stack with Docker Compose, including separate backend, worker, database, cache, vector-store, and frontend concerns.
- Added CI quality gates for linting, type checking, tests, frontend builds, and Docker Compose config validation.

## Backend Strengths

- Clear split between API routing, orchestration, retrieval, indexing, storage, workers, and observability.
- Background workers prevent slow durable writes from blocking user-facing QA responses.
- Trace IDs make it possible to connect an API request to queue events, worker logs, and database rows.
- Tests cover API error shape, retrieval smoke behavior, async indexing, worker idempotency, retries, and dead-letter behavior.

## Good Interview Talking Points

- Why Redis Streams were used instead of writing directly to MySQL on the request path.
- How idempotency keys prevent duplicate records when stream events are retried.
- How Chroma and MySQL serve different responsibilities in a RAG system.
- How Docker Compose separates local development from production-like images.
- How the smoke-check script verifies a running stack without relying on manual browser testing.
- What the next production hardening steps would be: auth, metrics, rate limits, managed secrets, and deeper integration tests.
