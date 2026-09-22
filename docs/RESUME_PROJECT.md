# Agent Studio resume material

Every sentence in this document must survive the question "where is that implemented?". The
[Evidence map](#evidence-map) at the end answers that per bullet. Numbers here were re-measured on this
checkout; none are borrowed from an older claim.

Claim discipline: do not replace "production-like" with "production-ready", do not describe OpenAI as
live-tested, and do not describe v1 as a public or multi-user service.

---

## A. 中文简历 · 项目名称与一句话

**项目名称**：Agent Studio — 可观测的 AI Agent 应用开发与调试平台

**一句话（69 字）**：

> 设计并实现全栈 AI Agent 平台：应用层有界执行循环统一模型决策、工具调用、RAG、持久记忆与评测，
> 每次运行都留下可追溯的执行证据。

**备用一句话（65 字，偏工程）**：

> 构建端到端 AI Agent 平台：应用层 AgentLoop 取代 SDK 策略，代次化 RAG 保证检索一致性，
> 数据库行锁保证记忆并发确定性。

**技术栈**：Python 3.12 · FastAPI · Pydantic · SQLAlchemy(async) · PostgreSQL 17 · pgvector 0.8.6 ·
Next.js · React · TypeScript(strict) · Tailwind CSS · Docker Compose · GitHub Actions · pytest · Vitest ·
Playwright · OpenAI Agents SDK(适配层) · DeepSeek Chat Completions

---

## B. 中文三条核心项目经历（最强版）

> 结构：动作 + 技术难点 + 解法 + 已验证结果。避免"负责/参与/熟悉"。

**1. 设计应用层可控的有界 Agent 执行循环，把产品策略从模型 SDK 中剥离**

难点在于 SDK 会把步数、重试、超时、终止态一并"接管"，换 Provider 就悄悄改变产品行为。解法是把
`AgentRuntime` / `LLMProvider` 定义成端口，由应用层 `AgentLoop` 独占步数上限、总超时、取消、无效输出
重试、重复调用抑制与终止映射，SDK 回调降级为 capture-only，模型选中的工具必须经 `ToolExecutor`
校验权限、超时与输出上限后才可执行。结果：Mock 与真实 DeepSeek 走同一条产品路径，离线套件
**206 项通过、26 项按标记排除**，且取消能抢占在途的 Provider 调用。

**2. 以"代次 + 原子激活"重构 RAG 摄入，杜绝失败或半成品数据污染检索**

难点在于"写向量再标记完成"没有新旧代次的边界：一次失败的重新摄入会留下既不属于旧版也不属于新版的
脏向量，而清理被中断还会留下孤儿向量，且检索路径分散在四处。解法是让分块以所属 `ingestion_job_id`
写入不相交的负索引区间暂存，激活时在同一事务内删除旧代次、归一化索引并置为 `completed`；四条检索
边界（SQLite 语义、pgvector 语义、混合检索词法侧、引用水合）各自独立要求所属任务为 `completed`。
结果：**27 个 RAG 测试**覆盖该不变量，其中 **11 个**直接针对代次一致性规则，历史遗留数据迁移采取
fail-closed。

**3. 用数据库行锁解决持久记忆与"关闭记忆"之间的并发竞争**

难点是"读策略标志再写入"即便在同一事务内也可能交错，导致重复写入或用户已关闭记忆后仍写入事实。
解法是让设置变更与运行终结在同一个 Agent 归属行上串行化——PostgreSQL 用 `SELECT ... FOR UPDATE`、
SQLite 用 `BEGIN IMMEDIATE`，且未知方言显式报错而非静默降级；终结逻辑在锁内读取策略后再决定是否
写入。结果：两种交错顺序被固化为确定行为（disable-wins / finalization-wins）并有专项测试断言，
终态事件与终态状态同事务提交，部分失败不会留下挂起的运行。

**可选第 4 条（偏交付与质量）**：

**4. 建立可复现的交付与质量证据链，而非依赖本地手工验证**

难点在于容器测试通过容易被叙述成"已部署"，而真实状态是没有镜像仓库、没有云端目标。解法是把
`DELIVERY READY` 严格定义为"该提交的生产镜像构建成功且一次性 Compose 运行时通过冒烟与 E2E"，CI 拆分为
Backend、PostgreSQL、Frontend、Playwright、Docker、Reliability、Performance 七个独立作业，真实
Provider 验证走手动受保护工作流并默认将密钥置空。结果：默认门禁无需密钥、不产生费用且确定性可复现，
一键 `docker compose up --build -d` 即可体验，无需安装 Python、Node 或 PostgreSQL。

---

## C. 技术要点速查（面试自用，非简历正文）

| 主题 | 一句话 |
|---|---|
| AgentLoop | 应用层拥有执行策略，SDK 只提供一次类型化决策 |
| 执行边界 | `max_steps` / `timeout_seconds` / `invalid_output_retries` / `max_context_chars` / `max_decision_chars` / `max_calls_per_tool`，全部带上下界校验 |
| 工具安全 | Registry 只登记不执行；Executor 独占校验与执行；SDK 回调 capture-only |
| RAG 一致性 | 代次暂存 + 单事务激活 + 四条检索边界独立要求 `completed` |
| Memory 并发 | Agent 行锁串行化策略变更与运行终结，未知方言 fail-closed |
| 事实来源 | `Run` + 有序 `RunEvent`（16 种已知事件类型）是唯一执行谱系，Dashboard 与评测都是投影 |
| 评测 | 真实运行 + evaluation-owned Agent 快照；`run_kind` 隔离，回归流量不污染使用指标 |
| 可观测性 | 事件先持久化再发布；脱敏在持久化前完成，存储与实时流数据一致 |
| 密钥边界 | 仅服务端环境/文件；Docker 助手经 stdin 写入 API 专属卷；无静默回退 |

---

## D. AI Application Engineer 版

**Project**: Agent Studio — full-stack AI agent application platform (FastAPI · Next.js · PostgreSQL/pgvector)

- Designed an application-owned bounded `AgentLoop` behind `AgentRuntime` / `LLMProvider` ports so execution
  policy — step limits, total timeout, cancellation that preempts an in-flight provider call, bounded
  invalid-output retry, duplicate-call suppression, typed termination — cannot drift with the model SDK;
  the same contract serves a deterministic Mock and a real DeepSeek adapter.
- Rebuilt knowledge ingestion around generation staging and atomic activation: chunks stage under a
  disjoint index range keyed to their owning ingestion job, activation deletes the prior generation and
  normalizes indices in one transaction, and all four retrieval boundaries independently require a
  `completed` job, so failed or orphaned data can never become a citation. 11 of the 27 RAG tests target
  this rule directly.
- Implemented Agent-scoped durable Memory with explicit write/retrieval/expiration/delete policy and
  database-enforced ordering: settings changes and Run finalization serialize on one Agent-owned row
  (`SELECT ... FOR UPDATE` / `BEGIN IMMEDIATE`, unknown dialects fail closed), with tests asserting both
  interleavings; persisted `Run` plus ordered `RunEvent` is the single lineage that trace, dashboard, and
  deterministic Evaluation all read.

## E. FDE / AI Solutions Engineer 版

**Project**: Agent Studio — deployable, debuggable AI agent stack

- Delivered the whole stack as a reproducible Docker Compose runtime: `git clone` then
  `docker compose up --build -d` starts the production Next.js server, one Uvicorn API process, and
  PostgreSQL 17 with pgvector — no local Python, Node, or database install, and no API key, because the
  default runtime is deterministic Mock.
- Integrated a second real provider without forking the runtime: an explicit provider resolver gives
  DeepSeek its own credentials, validated official base URL, bounded transport policy, and Chat
  Completions API style, persists `provider=deepseek` identity in every event, and never silently falls
  back to Mock or to OpenAI semantics — so a customer trace always answers "which provider actually ran".
- Made failures diagnosable instead of opaque: every transition is persisted as an ordered RunEvent with
  redacted payloads before it is streamed, restart behavior is defined per workload (Runs fail
  explicitly, ingestion requeues, Evaluation resumes), and the UI reports an API failure on any 5xx
  rather than inferring health from a reachable socket.

## F. AI Product / Technical Product 版

**Project**: Agent Studio — agent lifecycle product from definition to regression evidence

- Shipped one coherent lifecycle loop instead of disconnected screens: Agent Builder → Knowledge →
  Playground → Run Detail → Dashboard → Evaluations, where the trace a user debugs and the run a grader
  scores are the same persisted lineage, so a reported failure can be opened and explained.
- Defined the product boundary explicitly and defended it: v1 is a single-user local workbench, so
  authentication, RBAC, multi-tenancy, distributed workers, and Kubernetes were deliberately excluded and
  documented as **NOT IMPLEMENTED** rather than quietly implied — the same discipline keeps OpenAI at
  **LIVE NOT TESTED** while DeepSeek carries real validation.
- Made product quality measurable: evaluation traffic is isolated from usage metrics by `run_kind` so
  regression runs cannot distort success rate, evaluation suites snapshot their own Agent so tests cannot
  pollute the source Agent, and every capability carries a status plus evidence in a published matrix.

---

## G. English CV / LinkedIn

**Agent Studio — full-stack AI agent application platform** (personal project)

One-line: *A full-stack workbench for building, running, and debugging tool-using AI agents, where every
step, tool call, retrieval, and Memory write is persisted as ordered evidence that can be explained and
evaluated after the fact.*

- Built an application-owned bounded agent runtime (step limit, timeout, cancellation, bounded retry,
  typed termination) behind provider ports, keeping execution policy independent of the model SDK and
  letting a deterministic Mock and a real DeepSeek adapter share one product path.
- Designed generation-staged RAG with atomic activation and four independent completed-only retrieval
  boundaries, so failed or interrupted re-ingestion can never expose partial data or become a citation.
- Delivered durable Agent-scoped Memory with database-enforced concurrency ordering, plus Run/RunEvent
  observability and deterministic Evaluation over real isolated runs, packaged as a production-like
  Docker stack with non-root images and CI/Delivery gates.

**Tech**: Python, FastAPI, Pydantic, SQLAlchemy, PostgreSQL, pgvector, Next.js, React, TypeScript,
Tailwind CSS, Docker Compose, GitHub Actions, pytest, Vitest, Playwright, OpenAI Agents SDK, DeepSeek.

---

## H. Claims not to make

Do not claim enterprise or production readiness; authentication, RBAC, or multi-tenancy; Kubernetes;
distributed workers; public deployment; high availability; zero downtime; a production SLA; large-scale
concurrency; live OpenAI validation; published retrieval benchmarks; or users, stars, or traffic of any
kind.

---

## Evidence map

For interview preparation only — never paste this into a resume. Every bullet above maps to code, tests,
and docs in this repository.

| Resume claim | Source | Tests / evidence | Doc |
|---|---|---|---|
| Application-owned bounded AgentLoop behind ports | `apps/api/app/runtime/engine.py`, `apps/api/app/domain/contracts.py` (`RuntimeLimits`), `apps/api/app/runtime/providers.py` | `apps/api/tests/test_agent_loop.py` (15 tests incl. `test_max_steps_terminates_after_exact_limit`, `test_total_timeout_interrupts_provider`, `test_cancellation_interrupts_an_in_flight_provider_call`) | `docs/ADR/001-agent-runtime.md`, `docs/RUN_LIFECYCLE.md` |
| Capture-only SDK callbacks; only ToolExecutor executes | `apps/api/app/runtime/agents_sdk.py`, `apps/api/app/tools/registry.py` | `test_disabled_tool_hallucination_is_rejected_before_execution`, `test_duplicate_tool_call_is_not_executed_twice`, `test_per_tool_call_limit_blocks_changed_arguments` | `docs/MODEL_PROVIDERS.md` |
| Generation staging and atomic activation | `apps/api/app/knowledge/repository.py`, `apps/api/app/knowledge/service.py` | 11 of the 27 tests in `apps/api/tests/test_rag.py` target this rule, including `test_failed_reingestion_preserves_last_completed_generation`, `test_activation_failure_is_terminal_and_preserves_previous_generation`, and `test_activation_cleanup_never_rewrites_an_already_completed_job` | `docs/RAG_LIFECYCLE.md`, `docs/RAG_DESIGN.md` |
| Four independent completed-only retrieval boundaries | `apps/api/app/knowledge/vector_store.py`, `apps/api/app/knowledge/repository.py` | `test_failed_dirty_generation_is_invisible_to_every_retrieval_boundary`, `test_pgvector_search_query_requires_completed_generation` | `docs/RAG_DESIGN.md` |
| Legacy data migration fails closed | `apps/api/app/main.py` | `test_legacy_chunk_visibility_migration_is_fail_closed` | `docs/RAG_LIFECYCLE.md` |
| Memory row-lock ordering, fail-closed dialects | `apps/api/app/persistence/repositories.py` (`_serialized_agent_memory_transaction`, `_agent_row_statement`), `apps/api/app/memory/policy.py` | `test_disable_wins_serialization_before_run_finalization`, `test_finalization_wins_then_disable_blocks_future_writes`, `test_postgresql_memory_row_locks_prove_both_orderings` | `docs/MEMORY_DESIGN.md` |
| Terminal event and status commit together | `apps/api/app/persistence/repositories.py`, `apps/api/app/application/service.py` | `test_enabled_memory_and_terminal_state_commit_together`, `test_terminal_event_failure_rolls_back_memory_and_run_completion` | `docs/MEMORY_DESIGN.md` |
| One lineage; dashboard and Evaluation are projections | `apps/api/app/observability/aggregation.py`, `apps/api/app/persistence/repositories.py` (`list_runs` defaults to `RunKind.NORMAL`) | `apps/api/tests/test_observability.py`, `apps/api/tests/test_evaluation_api.py` | `docs/OBSERVABILITY_DESIGN.md`, `docs/EVALUATION_DESIGN.md` |
| Evaluation runs real isolated Runs on a snapshot | `apps/api/app/evaluation/service.py`, `apps/api/app/evaluation/graders.py` | `apps/api/tests/test_evaluation_api.py`, `apps/api/tests/test_evaluation_graders.py` | `docs/EVALUATION_DESIGN.md` |
| Redaction happens before persistence | `apps/api/app/observability/redaction.py` | `apps/api/tests/test_observability.py`, `test_unexpected_provider_exception_does_not_expose_secret_or_local_path` | `docs/SECURITY_DESIGN.md` |
| DeepSeek identity, own key, validated base URL, no fallback | `apps/api/app/runtime/providers.py`, `compose.deepseek.yaml`, `scripts/docker-up.ps1` | `apps/api/tests/real_deepseek/` (opt-in, `RUN_REAL_DEEPSEEK_TESTS=1`), `.github/workflows/provider-live.yml` | `docs/MODEL_PROVIDERS.md` |
| OpenAI implemented but live NOT TESTED | `apps/api/app/runtime/providers.py`, `apps/api/tests/real_openai/` | Offline contract tests only; `RUN_REAL_OPENAI_TESTS` defaults to `0` in `.github/workflows/ci.yml` | `docs/V1_STATUS.md`, `docs/OPENAI_INTEGRATION.md` |
| Seven independent CI jobs plus Delivery Validation | `.github/workflows/ci.yml`, `.github/workflows/delivery.yml` | Job names: Backend, PostgreSQL, Frontend, Playwright, Docker, Reliability, Performance | `docs/CI_RELIABILITY_PERFORMANCE.md` |
| Docker quick start needs no key and no local toolchain | `compose.yaml`, `apps/api/Dockerfile`, `apps/web/Dockerfile` | `docker compose config --quiet` passes; `scripts/docker-up.ps1` validates daemon, ports, Compose model, health | `docs/CONTAINER_RUNTIME.md`, `docs/DEMO.md` |
| 206 offline tests pass, 26 deselected | `apps/api/tests/`, `apps/api/pyproject.toml` | `pytest apps/api/tests -m "not postgresql and not real_openai and not real_deepseek and not performance" -q` | `README.md` |
| Typed `en` / `zh-CN` UI localization | `apps/web/i18n/` | `apps/web/i18n/i18n.test.tsx` incl. `keeps English and Chinese dictionary keys identical` | `docs/I18N.md` |
