# Agent Studio

Agent Studio is a development and debugging platform for building AI agents, attaching tools and knowledge, managing memory, executing runs, inspecting tool calls and traces, and evaluating behavior. It is not a ChatGPT clone.

The repository currently contains the engineering baseline and architecture decisions only. Agent Studio MVP functionality has not been implemented.

## Planned architecture

- `apps/web`: Next.js, React, TypeScript strict mode, Tailwind CSS
- `apps/api`: Python, FastAPI, Pydantic, SQLAlchemy
- `infra`: local PostgreSQL with pgvector through Docker Compose
- Agent runtime: hybrid architecture using the OpenAI Agents SDK behind application-owned ports

See [Architecture](docs/ARCHITECTURE.md) and [ADR-001](docs/ADR/001-agent-runtime.md) for the boundaries and rationale.

## Repository map

```text
apps/
  web/       planned frontend
  api/       planned API and agent runtime adapters
docs/        architecture, ADRs, development guidance, and verified baseline
infra/       infrastructure notes
tests/       future cross-application integration and E2E tests
```

## Development status

Read [Development](docs/DEVELOPMENT.md) before running planned commands and [Baseline](docs/BASELINE.md) for what has actually been verified. Most application commands are intentionally marked `NOT IMPLEMENTED` until their owning app is scaffolded.

## Security

Never commit API keys, tokens, credentials, private keys, cookies, local databases, or real environment files. Copy `.env.example` to a local ignored `.env` only when development begins, and replace every placeholder locally.
