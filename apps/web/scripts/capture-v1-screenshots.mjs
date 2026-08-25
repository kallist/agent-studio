import { chromium, request } from "@playwright/test";
import { mkdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repository = path.resolve(here, "../../..");
const assets = path.join(repository, "docs", "assets");
const demoDocument = path.join(repository, "docs", "demo", "agent-studio-demo-knowledge.md");
const webUrl = process.env.AGENT_STUDIO_SCREENSHOT_URL ?? "http://127.0.0.1:3000";
const screenshotUrl = new URL(webUrl);
if (!["127.0.0.1", "localhost"].includes(screenshotUrl.hostname)) {
  throw new Error("Screenshot capture is restricted to a loopback-only isolated stack.");
}

async function checked(response, expected) {
  if (!expected.includes(response.status())) {
    throw new Error(`${response.request().method()} ${response.url()} returned ${response.status()}: ${await response.text()}`);
  }
  return response.json();
}

async function pollJson(api, route, predicate, label) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const value = await checked(await api.get(route), [200]);
    if (predicate(value)) return value;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for ${label}.`);
}

async function createRun(api, agentId, input) {
  const created = await checked(await api.post(`/api/agents/${agentId}/runs`, { data: { input } }), [202]);
  return pollJson(api, `/api/runs/${created.id}`, (run) => ["completed", "failed", "cancelled"].includes(run.status), `Run ${created.id}`);
}

async function assertFreshIsolatedStack(api) {
  const [agents, bases, suites, dashboard] = await Promise.all([
    checked(await api.get("/api/agents"), [200]),
    checked(await api.get("/api/knowledge-bases"), [200]),
    checked(await api.get("/api/evaluation-suites"), [200]),
    checked(await api.get("/api/observability/dashboard"), [200]),
  ]);
  if (agents.length || bases.length || suites.length || dashboard.total_runs !== 0 || dashboard.recent_runs.length) {
    throw new Error("Screenshot capture requires a fresh isolated stack with no Agents, knowledge bases, Evaluation suites, or Runs.");
  }
}

async function seed(api) {
  await assertFreshIsolatedStack(api);
  const knowledgeBase = await checked(await api.post("/api/knowledge-bases", { data: { name: "Agent Studio Demo KB", description: "Safe v1 lifecycle demo facts" } }), [201]);
  if (knowledgeBase.embedding_provider !== "local") {
    throw new Error(`Screenshot capture requires local embeddings; received ${knowledgeBase.embedding_provider}.`);
  }

  const upload = await checked(await api.post(`/api/knowledge-bases/${knowledgeBase.id}/documents`, { multipart: { file: { name: "agent-studio-demo-knowledge.md", mimeType: "text/markdown", buffer: await readFile(demoDocument) } } }), [202]);
  await pollJson(api, `/api/ingestion-jobs/${upload.ingestion_job.id}`, (job) => job.state === "completed", "demo knowledge ingestion");

  const agent = await checked(await api.post("/api/agents", { data: {
    name: "Demo Lifecycle Agent",
    instructions: "Use Calculator for arithmetic and attached knowledge for grounded answers.",
    runtime_mode: "mock",
    model: null,
    tools: ["calculator", "knowledge_search"],
    knowledge_base_ids: [knowledgeBase.id],
    memory_enabled: true,
  } }), [201]);
  if (agent.runtime_mode !== "mock" || agent.model !== null) {
    throw new Error("Screenshot capture requires a verified Mock Agent with no provider model.");
  }

  const calculator = await createRun(api, agent.id, "Calculate 128 * 37 + 456");
  if (calculator.status !== "completed" || calculator.output !== "5192") throw new Error("Canonical Calculator demo did not return 5192.");
  await createRun(api, agent.id, "Remember that my preferred demo environment is PostgreSQL.");
  const grounded = await createRun(api, agent.id, "What demo environment do I prefer, and what recovery codename does the handbook use?");
  if (grounded.status !== "completed") throw new Error("Grounded Memory/RAG demo did not complete.");

  const suite = await checked(await api.post("/api/evaluation-suites", { data: {
    name: "v1 Demo Evaluation",
    description: "Canonical deterministic Calculator evidence",
    agent_id: agent.id,
    cases: [{
      name: "Calculator canonical result",
      input: "Calculate 128 * 37 + 456",
      graders: [
        { type: "contains", value: "5192", case_sensitive: true },
        { type: "tool_selected", tool_name: "calculator" },
      ],
    }],
  } }), [201]);
  const evaluation = await checked(await api.post(`/api/evaluation-suites/${suite.id}/runs`, { headers: { "Idempotency-Key": `v1-screenshot-${Date.now()}` } }), [202]);
  const completedEvaluation = await pollJson(api, `/api/evaluation-runs/${evaluation.id}`, (run) => ["completed", "failed", "cancelled"].includes(run.status), "v1 demo Evaluation");
  if (completedEvaluation.status !== "completed" || completedEvaluation.passed_cases !== 1) throw new Error("Canonical Evaluation did not PASS.");
  return { agent, calculator, grounded, suite, evaluation: completedEvaluation };
}

async function assertPage(page, heading, requireConnection = true) {
  await page.getByRole("heading", { name: heading, exact: true }).waitFor();
  if (requireConnection) await page.getByText("Connected", { exact: true }).first().waitFor();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  if (overflow) throw new Error(`${heading} has horizontal overflow at ${page.viewportSize()?.width}px.`);
}

async function capture(page, name) {
  const target = path.join(assets, name);
  await page.screenshot({ path: target, fullPage: false });
  const bytes = (await stat(target)).size;
  if (bytes > 2 * 1024 * 1024) throw new Error(`${name} exceeds the 2 MiB screenshot limit.`);
}

await mkdir(assets, { recursive: true });
const api = await request.newContext({ baseURL: webUrl });
const seeded = await seed(api);
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const page = await context.newPage();
const consoleErrors = [];
page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
page.on("pageerror", (error) => consoleErrors.push(error.message));

await page.goto(`${webUrl}/?view=dashboard`);
await assertPage(page, "Dashboard");
await page.getByText("Demo Lifecycle Agent", { exact: true }).first().waitFor();
await capture(page, "dashboard.png");

await page.goto(`${webUrl}/?view=playground&agent=${seeded.agent.id}&run=${seeded.calculator.id}`);
await assertPage(page, "Playground");
await page.getByText("5192", { exact: true }).first().waitFor();
await page.getByText("Tool call", { exact: true }).waitFor();
await capture(page, "playground-tool-call.png");

await page.goto(`${webUrl}/?view=playground&agent=${seeded.agent.id}&run=${seeded.grounded.id}`);
await assertPage(page, "Playground");
await page.getByText("Memory retrieved", { exact: true }).waitFor();
await page.locator(".trace-panel").getByRole("button", { name: "Knowledge / RAG", exact: true }).click();
await page.locator(".trace-citations").first().waitFor();
await capture(page, "rag-citation.png");

await page.goto(`${webUrl}/?view=run&agent=${seeded.agent.id}&run=${seeded.grounded.id}`);
await page.getByRole("heading", { name: "Execution timeline" }).waitFor();
await page.getByText("Memory Retrieved", { exact: true }).waitFor();
await capture(page, "run-trace.png");

await page.goto(`${webUrl}/?view=evaluations`);
await assertPage(page, "Evaluations");
const suiteRow = page.getByRole("row").filter({ hasText: "v1 Demo Evaluation" });
await suiteRow.locator(".eval-status").click();
await page.getByLabel("Evaluation summary").waitFor();
await page.locator(".evaluation-result-list").getByText("PASS", { exact: true }).waitFor();
await capture(page, "evaluation.png");

for (const view of ["Dashboard", "Agents", "Agent Builder", "Playground", "Evaluations"]) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: view, exact: true }).click();
  await assertPage(page, view, false);
}

if (consoleErrors.length) throw new Error(`Browser console errors:\n${consoleErrors.join("\n")}`);
await browser.close();
await api.dispose();
console.log("Captured five v1 screenshots and validated desktop/mobile overflow.");
