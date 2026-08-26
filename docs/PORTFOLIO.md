# Agent Studio portfolio summary

## English

Agent Studio is a development and debugging platform for observable AI Agent lifecycles. It lets a developer configure an Agent, attach safe tools and knowledge, run it with durable Memory, inspect persisted execution events and citations, and evaluate behavior through reproducible deterministic graders.

### Highlights

- Application-owned bounded AgentLoop and ToolExecutor instead of SDK-owned product policy.
- Completed-only RAG with PostgreSQL 17, pgvector `vector(256)`, HNSW, and source provenance.
- Agent-scoped durable Memory with explicit policy and tested transaction ordering.
- Run/RunEvent lineage shared by live trace, dashboard, and isolated Evaluation.
- Deterministic no-key demo plus real-tested DeepSeek integration.
- Production-like Docker runtime and GitHub CI/Delivery gates for real database, browser, recovery, and performance evidence.

### Stack

Next.js, React, TypeScript, Tailwind CSS, FastAPI, Pydantic, SQLAlchemy, pytest, Vitest, Playwright, PostgreSQL, pgvector, Docker Compose, GitHub Actions, OpenAI Agents SDK adapter, and DeepSeek.

### Engineering challenge

The central challenge was keeping application policy and reproducible evidence independent of provider SDK behavior. The design makes every tool call, retrieval, Memory action, and terminal outcome explainable without claiming unsupported production scale.

### Demo and links

- Demo: [DEMO.md](DEMO.md)
- Architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
- Source: `https://github.com/<owner>/agent-studio` (replace when publishing)

Resume-ready summary: Built a production-like local Agent lifecycle platform with bounded execution, safe tools, completed-only pgvector RAG, durable Memory, persisted observability, deterministic Evaluation, real-tested DeepSeek, and automated reliability/performance gates.

## 中文

Agent Studio 是一个面向 AI Agent 生命周期的开发与调试平台。开发者可以配置 Agent、挂载安全工具与知识库、使用持久化 Memory 执行任务，并通过 Run/RunEvent、引用来源和确定性 Evaluation 检查行为是否正确、可解释、可复现。

### 核心亮点

- 应用层拥有有界 AgentLoop、工具权限、超时、终止状态与事件顺序，而不是把产品策略交给 SDK。
- 基于 PostgreSQL 17 与 pgvector 的 completed-only RAG，包含 `vector(256)`、HNSW、混合检索与可追溯引用。
- Agent 级持久化 Memory，具有明确写入/检索/过期/删除策略和真实数据库并发验证。
- Run/RunEvent 是 Trace、Dashboard 与 Evaluation 的统一事实来源。
- 默认 Mock 无需 Key，DeepSeek 已做真实 API 验证；OpenAI 实时路径明确标记为 NOT TESTED。
- Docker production-like 本地运行时，以及覆盖数据库、浏览器、恢复和性能的 CI/Delivery 验证。

项目展示建议：先演示 Calculator 5192，再展示 RAG 引用与跨 Run Memory，随后打开 Run Detail 和 Evaluation PASS，最后用 Dashboard 总结完整生命周期。
