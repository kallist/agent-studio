# GitHub presentation

Recommended repository metadata and a pre-publish checklist for Agent Studio. These are recommendations
only: nothing in this document changes the GitHub repository, and no remote setting was modified while
preparing this packaging work.

Current state, read from the GitHub API and local git on the packaging branch:

| Item | Current value |
|---|---|
| Repository | `kallist/agent-studio` |
| Visibility | **private** |
| Default branch | `main` |
| Repository description | **empty** |
| Topics | **not set** |
| License | MIT |
| Latest release | `v1.0.0`, published, not a draft, not a prerelease |
| Tags | `v1.0.0` only |
| Workflows | `ci.yml` (CI), `delivery.yml` (Delivery Validation), `provider-live.yml` (manual only) |

Two consequences follow, and both matter more than wording:

1. **A private repository is invisible to anyone you have not invited.** No amount of README polish
   produces a 15-second impression for a recruiter until visibility changes. Decide deliberately whether
   to make it public before investing in social preview art.
2. **The description and topics are empty**, so GitHub search and the repository header currently say
   nothing about the project even to people who have access.

## Recommended repository description

Short enough for the repository header, natural to read, and carrying the real search terms:

> Full-stack workbench for building, running, and debugging tool-using AI agents: bounded agent runtime,
> RAG with citations, durable memory, persisted run traces, and deterministic evaluation.

A tighter variant if the header truncates:

> Build, run, and debug tool-using AI agents: bounded runtime, RAG with citations, durable memory, run
> traces, and deterministic evaluation.

Both stay accurate: no user counts, no traffic, no production claim, no benchmark figure.

## Recommended topics

GitHub allows up to 20 topics. These 15 are all genuinely relevant to what the repository contains:

```text
ai-agents  agentic-ai  llm  rag  retrieval-augmented-generation
fastapi  nextjs  typescript  python  postgresql
pgvector  docker  observability  evaluation  llmops
```

Deliberately omitted:

- `production-ready`, `enterprise`, `kubernetes`, `microservices` — v1 is a single-user local workbench
  and none of those describe it.
- `openai` — the OpenAI path is implemented but its live execution is **NOT TESTED**; `llmops` and
  `ai-agents` describe the repository more honestly. `deepseek` is a legitimate addition if you want the
  real-tested provider represented.

## Recommended pinned-repository description

If this is pinned on a profile, the pin shows the repository description. Use a version that reads well
without surrounding context:

> A local Agent development workbench that makes agent runs observable and reproducible: application-owned
> bounded runtime, generation-consistent RAG, durable memory, and deterministic evaluation. Mock by
> default, no API key needed.

## Recommended social preview

GitHub's social preview is a 1280×640 image shown when the repository link is shared. Whether one is
currently configured is **NOT VERIFIED** — the public REST API does not expose that field.

Recommended composition, using only real project assets:

- A real Studio screenshot cropped to the upper portion of the UI, where the sidebar and the dashboard
  metrics are both readable. `docs/assets/dashboard.png` is a 1440×900 capture and crops cleanly at this
  ratio.
- The title `Agent Studio` and one subtitle line: *Observable, reproducible AI agent runs*.
- No stock art, no device mockups, no generated imagery.

Do not create a stylized or AI-generated cover: the screenshot is the credible asset, and a fake UI image
would contradict the project's own honesty discipline.

## Pre-publish checklist

Run through this before treating the repository as portfolio-facing.

### Presentation

- [ ] Repository description set from the recommendation above.
- [ ] Topics set (15 recommended, none overstating maturity).
- [ ] README renders correctly on GitHub: Mermaid diagram renders, badges resolve, all five screenshots load.
- [ ] README first screen readable without scrolling: title, positioning, badges, one paragraph, hero image.
- [ ] Social preview image configured (1280×640) using a real screenshot.
- [ ] Repository pinned on the profile with a description that stands alone.

### Content

- [ ] `docs/` index reachable from the README documentation section.
- [ ] Architecture, Run lifecycle, and RAG lifecycle diagrams render.
- [ ] Case study present and free of claims the code does not support.
- [ ] Every capability status matches `docs/V1_STATUS.md`.
- [ ] "NOT TESTED" appears wherever it must: OpenAI live paths, horizontal operation, managed PostgreSQL,
      internet load, SLA.

### Access and process

- [ ] Visibility decision made deliberately. If the repository becomes public, remember that history,
      issues, and pull requests become visible too.
- [ ] Branch protection on `main` requires the seven CI job names: `Backend`, `PostgreSQL`, `Frontend`,
      `Playwright`, `Docker`, `Reliability`, `Performance`.
- [ ] GitHub Actions has run at least once on `main` so the two badges are not grey.
- [ ] Provisioning a future release follows the existing tag convention and links `docs/RELEASE_NOTES_v1.0.md`.

### Safety

- [ ] Secret scan clean: no API keys, tokens, credentials, connection strings, or `.env` content in the
      tree, screenshots, docs, or git history.
- [ ] No private absolute paths anywhere in published files: no `C:\Users\...`, no `C:\aiwork\...`, no
      `.codex/worktrees`, no machine names, no usernames.
- [ ] Screenshots contain no browser chrome, terminal output, tokens, or personal data.
- [ ] `.env.example` contains placeholders only.
- [ ] No local database, cache, or test-run artifact is tracked.

## Notes for later

- **Release page.** `v1.0.0` already carries structured highlights and a limitations link, so it reads
  clearly as it stands. Published releases should not be silently rewritten; if the wording is ever
  revised, do it in a new release that references this one.
- **Conventional commits and PR history.** The `feat:` / `fix:` / `docs:` / `chore:` prefixes are
  consistent and useful, but most feature work arrived as a single large commit per branch, so the commit
  log is not a fine-grained development narrative. Worth changing going forward, not worth rewriting.
- **One early commit has a malformed message** (`a1e5b54`), whose subject is a directory tree rather than
  a description. History rewriting is not recommended, and the artifact it introduced has been removed.
- **Sub-directory READMEs** (`apps/api`, `apps/web`, `infra`, `tests`) are short directional pointers
  rather than second READMEs, which is the right shape. `apps/api` and `tests` previously still claimed
  `NOT IMPLEMENTED` from the repository-start baseline and have been corrected; keep the rest factual as
  the project moves, and do not grow any of them into a duplicate of the root README.
