# Project Mission

Agent Studio is a development and debugging platform for creating and configuring AI agents, attaching tools, adding knowledge bases and RAG, managing memory, executing agents, inspecting runs, tool calls, and traces, and evaluating agent behavior.

It is not a ChatGPT clone. The product exists to make agent behavior observable, testable, explainable, and reproducible.

# Product Principles

Apply this priority order:

1. Correct
2. Runnable
3. Testable
4. Explainable
5. Maintainable
6. Visually polished

Do not sacrifice real behavior for a UI demo. Do not present large static mock datasets, invented metrics, fake traces, or fake tool calls as implemented functionality.

# Architecture Rules

Read `docs/ARCHITECTURE.md` and relevant ADRs before changing boundaries.

## Frontend

- Use Next.js, React, TypeScript strict mode, and Tailwind CSS.
- Prefer accessible native elements and a small, selectively adopted component layer such as shadcn/ui primitives. Do not import a large component suite by default.
- Keep API types explicit, server/client boundaries clear, and state ownership local and intentional.
- Do not put substantial business logic in React components.

## Backend

- Use Python, FastAPI, Pydantic, and SQLAlchemy.
- Keep route handlers thin. Application workflows belong in services; domain rules do not belong in HTTP handlers or ORM models.
- Use type annotations, explicit exception types, consistent async patterns, and deliberate dependency injection.
- Do not silently swallow errors or use broad `except Exception: pass` handling.

## Data and retrieval

- Prefer PostgreSQL through Docker Compose for development.
- Prefer PostgreSQL with pgvector for the first vector retrieval implementation.
- Keep repositories and `VectorStore` behind ports so business logic is not tied to PostgreSQL, pgvector, or SQLite.
- SQLite is an explicitly documented temporary fallback only when PostgreSQL blocks a vertical slice. Do not leak SQLite-specific behavior into application logic.

## Agent runtime and AI providers

- Follow `docs/ADR/001-agent-runtime.md`: use a hybrid runtime architecture.
- Keep the OpenAI Agents SDK inside an `AgentRuntime` adapter. Persistence, evaluation, knowledge, application-specific tracing, and product policy remain application-owned.
- Route model access through `LLMProvider`; do not scatter SDK or provider calls through business code.
- Provide an `OpenAIProvider` for real execution and a deterministic `MockProvider` for tests and the calculator demo.
- Unit tests, primary integration paths, and the calculator demo must run without a real API key.

## Testing

- Backend: pytest.
- Frontend: Vitest and React Testing Library unless an implementation ADR changes the choice.
- End-to-end: Playwright.
- Install and configure test tools as project dependencies when the relevant app is scaffolded. Never claim globally visible tools are project test configuration.

# Coding Rules

## Python

- Type public interfaces and non-trivial local values.
- Use Pydantic schemas at input/output boundaries.
- Keep async usage consistent across call chains.
- Raise explicit, meaningful exceptions and translate them at boundaries.
- Keep business logic out of route handlers.

## TypeScript

- Keep `strict` enabled and avoid `any`.
- Model API contracts explicitly.
- Keep server and client components clearly separated.
- Avoid giant components; extract by responsibility, not by arbitrary size.

## General

Avoid meaningless abstractions, premature microservices, giant services, copy-paste implementations, and fake TODO completion. Prefer the smallest boundary that protects a real variation point or test seam.

# Agent Development Rules

For each feature:

1. Read the relevant code and project instructions.
2. Search for existing implementations and call sites.
3. Understand dependencies and boundaries.
4. Define the smallest safe change.
5. Implement it.
6. Run applicable tests.
7. Review the complete diff.
8. Run applicable build, lint, typecheck, security, and UI checks.

For a bug fix, establish the root cause first. Never make tests pass by deleting or skipping tests, weakening assertions, or catching and ignoring failures.

# Development tooling rules

A tool appearing in an agent or editor catalog is not proof that it is connected or usable. Verify with a real call before relying on it.

## OpenAI and Agents SDK documentation

- For OpenAI API, Responses API, Agents SDK, tool calling, structured output, streaming, or other version-sensitive behavior, verify current official OpenAI documentation rather than relying on training data.
- Do not adopt the Agents SDK merely because it is available. Preserve the hybrid boundary in ADR-001 unless a new ADR replaces it.

## Browser and UI verification

- After implementing a UI feature, open the running app, exercise real interactions, inspect DOM and console errors, capture evidence when useful, and perform responsive QA.
- Source inspection alone is not UI validation.

# Security Rules

Never commit `.env`, API keys, OAuth tokens, private keys, credential JSON, cookies, provider secrets, or sensitive local databases. `.env.example` may contain names and placeholders only.

Every tool must define or enforce appropriate permissions, timeouts, argument validation, output-size limits, and error handling. HTTP tools must defend against SSRF. File tools must defend against path traversal.

# Definition of Done

A feature is complete only after all applicable build, lint, typecheck, unit, integration, E2E, browser validation, error-state, loading-state, and documentation checks pass.

If a check does not exist or was not run, write `NOT TESTED`. Never infer that it passed.
