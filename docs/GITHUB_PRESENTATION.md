# GitHub presentation

Repository metadata and a pre-publication checklist for Agent Studio, recorded as a factual snapshot
rather than as a set of recommendations. The values below were read back from the GitHub API after the
metadata was applied.

Current state, read from the GitHub API:

| Item | Value |
|---|---|
| Repository | `kallist/agent-studio` |
| Visibility | **public** |
| Default branch | `main` |
| Repository description | *Full-stack workbench for building, running, and debugging tool-using AI agents: bounded agent runtime, RAG with citations, durable memory, persisted run traces, and deterministic evaluation.* |
| Topics | 16 set (see below) |
| License | MIT, detected by GitHub from `LICENSE` |
| Latest release | `v1.0.0`, published, not a draft, not a prerelease |
| Tags | `v1.0.0` only |
| Homepage | intentionally empty — there is no live hosted product, and a placeholder URL would be a false claim |
| Workflows | `ci.yml` (CI), `delivery.yml` (Delivery Validation), `provider-live.yml` (manual only) — all `active` |

The description and topics deliberately avoid `production-ready`, `enterprise-grade`, `kubernetes`, and
`microservices`: v1 is a single-user local workbench and none of those describe it. `openai` is also
absent because that live path is **NOT TESTED**; `deepseek` is present because it carries real online
validation.

## Topics applied

```text
agentic-ai, ai-agents, deepseek, docker, evaluation, fastapi, llm, llmops,
nextjs, observability, pgvector, postgresql, python, rag,
retrieval-augmented-generation, typescript
```

## Alternative descriptions

Kept for future edits. The applied description is the first of these.

A tighter variant if the header truncates:

> Build, run, and debug tool-using AI agents: bounded runtime, RAG with citations, durable memory, run
> traces, and deterministic evaluation.

Both stay accurate: no user counts, no traffic, no production claim, no benchmark figure.

## Pinned-repository description

If this repository is pinned on the profile, the pin shows the repository description. A version that
reads well without surrounding context:

> A local Agent development workbench that makes agent runs observable and reproducible: application-owned
> bounded runtime, generation-consistent RAG, durable memory, and deterministic evaluation. Mock by
> default, no API key needed.

This is a manual profile step, not a repository setting.

## Social preview

GitHub's social preview is a 1280×640 image shown when the repository link is shared. Whether a custom one
is configured is **NOT VERIFIED** — the REST API does not expose that field, and when it is unset GitHub
falls back to generating a card from the README, which already shows the project title, description, and
hero screenshot.

If you want an explicit image, build it from real assets only:

- A real Studio screenshot cropped to the upper portion of the UI, where the sidebar and the dashboard
  metrics are both readable. `docs/assets/dashboard.png` is a 1440×900 capture and crops cleanly at this
  ratio.
- The title `Agent Studio` and one subtitle line: *Observable, reproducible AI agent runs*.
- No stock art, no device mockups, no generated imagery.

Do not create a stylized or AI-generated cover: the screenshot is the credible asset, and a fake UI image
would contradict the project's own honesty discipline. This is a manual web-UI step.

## Pre-publication checklist

Completed items reflect what was actually verified before the repository was made public on
2026-09-22; the remaining boxes are manual steps or deliberate non-goals.

### Presentation

- [x] Repository description set (applied, read back from the API).
- [x] Topics set: 16, none overstating maturity (applied, read back from the API).
- [x] README renders correctly on GitHub: badges resolve (all four return 200), all five screenshots load
      (each fetched anonymously from `raw.githubusercontent.com` at 200).
- [x] README first screen readable without scrolling: title, positioning, scope disclaimer, four badges,
      and quick links all appear before the hero image at line 34.
- [ ] Social preview image configured (1280×640). **Manual step** — see above.
- [ ] Repository pinned on the profile. **Manual step** — profile-level, not a repository setting.

### Content

- [x] `docs/` index reachable from the README documentation section.
- [x] Architecture, Run lifecycle, and RAG lifecycle diagrams present and balanced.
- [x] Case study present and free of claims the code does not support.
- [x] Every capability status matches `docs/V1_STATUS.md`.
- [x] "NOT TESTED" appears wherever it must: OpenAI live paths, horizontal operation, managed PostgreSQL,
      internet load, SLA.
- [x] `README.zh-CN.md` exists with the same badges, numbers, section count, and the same 11 capability
      statuses as the English README.

### Access and process

- [x] Visibility decision made deliberately, and the consequences reviewed first: history, issues, and
      pull requests became visible at the same moment.
- [ ] Branch protection on `main` requires the seven CI job names: `Backend`, `PostgreSQL`, `Frontend`,
      `Playwright`, `Docker`, `Reliability`, `Performance`. **Manual step** — repository settings.
- [x] GitHub Actions has run on `main` since publication, so both badges are live rather than grey: the
      post-merge CI and Delivery Validation runs both succeeded.
- [ ] Provisioning a future release follows the existing tag convention and links
      `docs/RELEASE_NOTES_v1.0.md`. Nothing was tagged or released as part of making this repository public.

### Safety

- [x] Secret scan clean across the working tree and every commit's tree: no API keys, tokens, credentials,
      connection strings, or `.env` content.
- [x] No private absolute paths in published files. The only matches in history are a test sentinel that
      asserts such paths never leak into serialized output, this checklist's own wording, and
      `docs/BASELINE.md`, which has since been removed from the tree.
- [x] Screenshots contain no browser chrome, terminal output, tokens, or personal data; all five are
      1440×900 captures produced by the checked-in capture script.
- [x] `.env.example` contains placeholders and empty values only.
- [x] No local database, cache, or test-run artifact is tracked.

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
