# Codex capability inventory

Audit date: 2026-08-13 (Asia/Shanghai)

Workspace: `C:\aiwork\agent-studio`

Scope: capabilities actually visible or callable in this Codex Desktop session. Presence in a catalog is not treated as proof of a working connection.

This is a point-in-time environment audit. Later repository changes, including the engineering baseline and project instructions, are recorded in `BASELINE.md` and `AGENTS.md` rather than retroactively presented as capability-audit results.

## Audit rules

- A capability is **verified** only when its file, executable, runtime, connector, or read-only API call succeeded in this session.
- **Installed but blocked** means the plugin/skill exists, but its external account or live session is unavailable.
- No API key, OAuth token, credential, cookie, or secret value is recorded here.
- This audit does not authorize publishing, deployment, external writes, account changes, or destructive actions.

## Repository and instructions

- Git was not present in this directory at audit start. It was initialized with branch `main`.
- At audit start, no `AGENTS.md` was found in `C:\aiwork\agent-studio`, `C:\aiwork`, or `C:\`. The later engineering-baseline phase added the repository-level `AGENTS.md`.
- The workspace was empty before initialization. No test configuration, package manifest, application framework, or business code existed.

## Skills

SkillDeck successfully enumerated **69 distinct local skills** from personal, system, and installed-plugin sources. The most relevant operational Skill files were read during initialization: OpenAI Docs, Browser, Computer Use (plus guidance/API/confirmation policy), GitHub, Documents, Spreadsheets, Presentations, PDF, Image Generation, Chrome control, and Sites building.

### System and personal skills

- `openai-docs` — current official OpenAI/Codex documentation and setup guidance.
- `imagegen` — generate or edit raster assets; built-in image generation is available without storing a project API key.
- `plugin-creator` — scaffold Codex plugins when the project later needs one.
- `skill-creator` — create or update reusable Codex skills.
- `skill-installer` — install curated or repository-hosted skills.
- `review-agent` — structured review workflow.
- `pdf` — inspect, create, render, fill, and visually verify PDFs.

### Browser, desktop, and web delivery skills

- `control-in-app-browser` — browser navigation, DOM inspection, Playwright-style interaction, screenshots, and local web QA.
- `control-chrome` — external Chromium-family browser control when a supported extension connection exists.
- `computer-use` — Windows application automation through native window targeting and screenshots.
- `sites-building`, `sites-hosting` — build and host Sites projects when selected; no site was created in this initialization.
- `visualize` — interactive in-conversation diagrams, charts, simulations, and UI mockups.

### Documents, sheets, slides, and templates

- `documents`, `spreadsheets`, `excel-live-control`, `presentations` — create/edit/verify Office artifacts; live Excel requires a connected document session.
- Template skills: `artifact-template-analytics-dashboard`, `artifact-template-business-review`, `artifact-template-design-report`, `artifact-template-experiment-analysis`, `artifact-template-financial-budget`, `artifact-template-investment-committee-memo`, `artifact-template-legal-memorandum`, `artifact-template-market-trends-report`, `artifact-template-minimal-letterhead`, `artifact-template-operating-calendar`, `artifact-template-operating-review`, `artifact-template-project-kickoff`, `artifact-template-project-tracker`, `artifact-template-sales-pipeline`, `artifact-template-simple-dark-mode`, `artifact-template-simple-light-mode`, `artifact-template-strategy-memorandum`, `artifact-template-system-design`, `artifact-template-team-alignment`, and `artifact-template-three-statement-forecast`.

### GitHub skills

- `github` — repository/PR/issue orientation through the GitHub connector.
- `gh-address-comments` — address PR review threads.
- `gh-fix-ci` — diagnose GitHub Actions failures using connector context plus `gh` logs.
- `yeet` — intentionally commit, push, and open a draft PR after user authorization.

### Data Analytics skills

- Routing/context: `index`, `gather-business-context`, `create-data-context`.
- Analysis: `analyze-data-quality`, `product-business-analysis`, `metric-diagnostics`, `market-sizing`, `design-kpis`.
- Delivery: `build-dashboard`, `build-report`, `kpi-reporting`, `visualize-data`, `jupyter-notebooks`, `validate-data`, `publish-artifact-to-sites`.

### Canva skills

- `canva-brand-check`, `canva-branded-presentation`, `canva-bulk-create`, `canva-design-feedback`, `canva-edit-design`, `canva-implement-feedback`, `canva-resize-for-social-media`, `canva-translate-design`.
- These skills are installed, but the Canva connector currently requires reauthentication; they are not usable until that connection is repaired.

### OpenAI developer plugin skills

- `agents-sdk`, `build-chatgpt-app`, `chatgpt-app-submission`, `openai-api-troubleshooting`, `openai-platform-api-key`.
- Intended project use: only if Agent Studio later integrates OpenAI APIs, the Agents SDK, or a ChatGPT app. No API key was requested, created, read, or saved in this initialization.

## Installed plugin skill sources

SkillDeck verified local skill sources for these installed plugin families:

1. Spreadsheets
2. Presentations
3. PDF
4. Documents
5. OpenAI Developers
6. Default/OpenAI Templates
7. GitHub
8. Data Analytics
9. Canva
10. Visualize
11. Sites
12. Computer Use
13. Chrome
14. Browser

SkillDeck itself is also callable as an MCP plugin and provides skill enumeration plus a visual skill console.

## Connectors and apps

| Connector/app | Status verified in this session | Potential Agent Studio use |
|---|---|---|
| GitHub | **Connected**. Read-only identity call returned login `kallist`; GitHub CLI is also authenticated. | Repository discovery, issues, PRs, review threads, CI context, and later publishing with explicit authorization. |
| Sites | **Connected/callable**. Listing sites succeeded and returned an empty list. | Optional future web preview/deployment; not selected or used now. |
| Canva | **Installed but blocked**. A read-only search returned `UNAUTHORIZED` and requires reauthentication. | Design generation/review after reauthentication. |
| Codex Document Control | **Callable, no live session**. Session enumeration succeeded with zero Excel/PowerPoint/Sheets sessions. | Live Office control only after the user connects a document session. |
| Data Analytics widgets | **Tool surface present** (render table/chart/artifact, validate/export artifact package). | Render analysis artifacts after data workflows exist. |
| Default Templates | **Installed resource/skills present**. | Consistent document, deck, and spreadsheet starting points. |

No Gmail, Google Drive, Notion, Slack, Figma, database SaaS, or other catalog-only connector is claimed as installed or connected. The recommended-plugin catalog is not proof of access.

## MCP

The current tool registry exposes **164 MCP tools** across four MCP servers:

- `codex_apps`: 154 tools
  - GitHub: 89
  - Canva: 32
  - Sites: 20
  - Codex Document Control: 3
  - Plugin management: 4
  - Safety settings: 5
  - Local hotline lookup: 1
- `dataAnalyticsWidgets`: 5 tools (`render_table`, `render_chart`, `render_artifact`, `validate_artifact`, `export_artifact_package`)
- `node_repl`: 3 tools (`js`, module-directory registration, reset)
- `skilldeck_mcp`: 2 tools (list skills, open SkillDeck)

MCP resource enumeration also exposed plugin/skill resources and Data Analytics/SkillDeck widgets. No parameterized MCP resource templates were returned.

Project use: MCP is the integration boundary for connected services and rich widgets. External write operations must remain user-directed and narrowly scoped.

## Browser and Computer Use

### Browser

- The Browser plugin runtime loaded successfully.
- The Codex in-app browser was selected, returned its full control documentation, opened the official Codex documentation, and read the resulting title/URL.
- Browser discovery returned one in-app browser plus two connected Edge extension instances.
- No connected Chrome-family instance was returned, even though the Chrome skill is installed. Therefore Chrome itself is not claimed as currently connected.
- Supported project use includes local web testing, DOM inspection, responsive QA, screenshots, console-log inspection, and Playwright-style interaction.

### Computer Use

- `@oai/sky` imported successfully and `list_apps()` returned 40 applications and 6 currently targetable windows.
- This proves that Windows app enumeration is working. No window input was sent during the audit.
- Intended use is end-to-end Windows UI verification when browser or direct file tools are insufficient. Terminal and Codex UI automation are prohibited by the Computer Use safety policy.

## Documentation and artifact tools

The Codex bundled workspace runtime loaded successfully (bundle `26.805.11740`):

- Node.js 24.14.0 with `@oai/artifact-tool`, `docx`, `pdf-lib`, `pdfjs-dist`, and `playwright` packages.
- Python 3.12.13 with `pypdf`, `pdfplumber`, `reportlab`, `python-docx`, `pandas`, and `numpy`.
- Poppler wrappers `pdftoppm` and `pdfinfo` are available.
- `soffice` was not found on `PATH`; DOCX/PPTX render workflows must verify the bundled/helper route at task time and must not claim LibreOffice visual QA unless rendering actually succeeds.

Project use: specifications, reports, workbooks, decks, and PDFs can be produced later with their mandatory render-and-verify workflows.

## Testing tools

- Shell execution, `rg`, Git, Node/npm/pnpm/npx, bundled Python, Docker CLI, Java, Maven, and the .NET host are present.
- Browser runtime includes Playwright and supports DOM/UI testing through the Browser plugin.
- PowerShell Pester 3.4.0 is installed.
- `pytest`, Vitest, Jest, and `@playwright/test` are not installed in the checked runtimes.
- No project test configuration exists yet, so no test suite could be executed.

Project use: select and install only the test stack that matches the eventual architecture; do not infer a framework from globally available tools.

## UI and design tools

- Verified available: Image Generation tool, local image viewer, web image search, Visualize skill, Browser screenshots/DOM inspection, Data Analytics chart widgets, Sites, and Canva tool schemas.
- Canva is currently blocked by reauthentication, as noted above.
- These tools can support future UI concepts, raster assets, interactive explainers, charts, and visual QA. No design or application UI was created in this initialization.

## Database tools

- No database connector or SaaS database plugin is currently installed/connected.
- Command-line clients `sqlite3`, `psql`, `mysql`, `mongosh`, and `redis-cli` were not found.
- Bundled Python's standard `sqlite3` module is functional (SQLite 3.50.4, verified with an in-memory query).
- Sites can support managed persistence when explicitly chosen in a future Sites project, but no database or schema exists now.

Project use: local SQLite prototyping is possible through bundled Python. A production database must be selected deliberately; no credentials or connection strings should be committed.

## Git and GitHub tools

- Git 2.40.1 is available; this repository is initialized on `main`.
- GitHub CLI 2.97.0 is installed and authenticated as `kallist` using the system credential store. The credential value was not captured or saved.
- The GitHub connector is callable and exposes repository, issue, PR, review, reaction, workflow, and file/commit operations.
- During the capability-audit phase, no remote was added, no commit was created, nothing was pushed, and no PR/issue was modified.

## Security and secret handling

- Never commit `.env`, private keys, credential JSON, tokens, cookies, local database files, or provider configuration containing secrets.
- Keep example configuration in `.env.example` with placeholder values only.
- Use existing OS/app credential stores or approved connector authentication.
- Inspect staged changes before every commit, and run an appropriate secret scan once a project toolchain is selected.

## Current limitations requiring future action

- Canva must be reauthenticated before use.
- Live Excel/PowerPoint/Google Sheets control requires an active Codex Document Control session.
- Chrome-family browser control is not currently connected; the in-app browser and Edge extension connections are available.
- No production database connector is installed.
- No project-specific build, lint, unit-test, integration-test, or E2E framework exists yet.
- Repository-level agent conventions were outside the capability-audit phase and were subsequently added by the engineering baseline.
