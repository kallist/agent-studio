import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const onlineEnabled = process.env.RUN_REAL_DEEPSEEK_TESTS === "1";
const keyConfigured = Boolean(process.env.DEEPSEEK_API_KEY?.trim());
const model = process.env.DEEPSEEK_REAL_TEST_MODEL?.trim()
  || process.env.DEEPSEEK_MODEL?.trim()
  || "deepseek-v4-flash";

test.skip(!onlineEnabled, "Real DeepSeek E2E requires RUN_REAL_DEEPSEEK_TESTS=1.");
test.skip(!keyConfigured, "Real DeepSeek: BLOCKED — DEEPSEEK_API_KEY not configured");
test.describe.configure({ mode: "serial" });
test.setTimeout(120_000);

async function selectDeepSeek(page: Page): Promise<void> {
  await page.getByRole("radio", { name: /DeepSeek/ }).check();
  await page.getByLabel("Model").fill(model);
}

test("runs a streamed real DeepSeek basic response and renders normalized usage", async ({ page }) => {
  await page.goto("/?view=builder");
  await page.locator(".builder-form").getByRole("textbox", { name: /^Name/ }).fill(`Real DeepSeek ${Date.now()}`);
  await page.locator(".builder-form").getByRole("textbox", { name: /^Prompt/ }).fill("Reply with exactly REAL_DEEPSEEK_OK and nothing else.");
  await selectDeepSeek(page);
  await page.getByLabel("Enable Calculator").uncheck();
  await page.getByLabel("Enable Durable Memory").uncheck();
  await page.getByRole("button", { name: "Save agent" }).click();

  await page.getByLabel("Message").fill("Return the validation token now.");
  await page.getByRole("button", { name: "Run agent" }).click();
  await expect(page.getByText("REAL_DEEPSEEK_OK", { exact: true }).first()).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Run detail", exact: true }).click();
  const metrics = page.getByLabel("Observability metrics");
  await expect(metrics).toContainText("Provider Requests1");
  await expect(metrics).not.toContainText("Total TokensN/A");
  const inspector = page.locator(".run-inspector");
  await expect(inspector).toContainText("Runtimeagents_sdk");
  await expect(inspector).toContainText("Providerdeepseek");
  await expect(inspector).toContainText("API stylechat_completions");
  await expect(inspector).toContainText(`Model${model}`);
});

test("runs a true DeepSeek calculator tool call through the application executor", async ({ page }) => {
  await page.goto("/?view=builder");
  await page.locator(".builder-form").getByRole("textbox", { name: /^Name/ }).fill(`DeepSeek Calculator ${Date.now()}`);
  await page.locator(".builder-form").getByRole("textbox", { name: /^Prompt/ }).fill("For arithmetic, call calculator exactly once and then return only its exact result.");
  await selectDeepSeek(page);
  await page.getByLabel("Enable Durable Memory").uncheck();
  await page.getByRole("button", { name: "Save agent" }).click();

  await page.getByLabel("Message").fill("Use the calculator tool to compute: 128 * 37 + 456");
  await page.getByRole("button", { name: "Run agent" }).click();
  await expect(page.locator(".chat-message.agent .agent-answer p").last()).toContainText("5192", { timeout: 60_000 });
  await expect(page.getByText("Tool call", { exact: true })).toBeVisible();
  await expect(page.getByText("Tool result", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Run detail", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Tool Call" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tool Result" })).toBeVisible();
  await expect(page.getByLabel("Observability metrics")).toContainText("Tool Calls1");
  await expect(page.getByLabel("Observability metrics")).toContainText("Provider Requests2");
  await expect(page.locator(".execution-timeline")).toContainText("5192");
});

test("runs real DeepSeek with local RAG and citations", async ({ page }) => {
  const baseName = `Real DeepSeek RAG ${Date.now()}`;
  await page.goto("/?view=builder");
  await page.getByLabel("Knowledge base name").fill(baseName);
  await page.getByLabel("Description").fill("Bounded DeepSeek RAG validation");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByRole("button", { name: new RegExp(baseName) })).toBeVisible();

  const fixture = path.resolve(process.cwd(), "../../tests/fixtures/rag/security_policy.txt");
  await page.locator('input[type="file"]').setInputFiles(fixture);
  await page.getByRole("button", { name: "Upload & ingest" }).click();
  await expect(page.getByText("completed", { exact: true })).toBeVisible();
  await page.getByRole("checkbox", { name: new RegExp(baseName) }).check();
  await page.locator(".builder-form").getByRole("textbox", { name: /^Name/ }).fill(`DeepSeek RAG Agent ${Date.now()}`);
  await page.locator(".builder-form").getByRole("textbox", { name: /^Prompt/ }).fill("For knowledge questions, call knowledge_search exactly once and answer from its cited result.");
  await selectDeepSeek(page);
  await page.getByLabel("Enable Calculator").uncheck();
  await page.getByLabel("Enable Durable Memory").uncheck();
  await page.getByRole("button", { name: "Save agent" }).click();

  await page.getByLabel("Message").fill("How are parser failures isolated?");
  await page.getByRole("button", { name: "Run agent" }).click();
  await expect(page.locator(".chat-message.agent .agent-answer p").last()).toContainText(/parser/i, { timeout: 60_000 });
  const citation = page.locator(".trace-citations").getByText(/security_policy\.txt · score/).first();
  await expect(citation).toBeVisible();
  await citation.click();
  await expect(page.locator(".trace-citations")).toContainText("upload://security_policy.txt");
});

test("retrieves application-owned durable Memory for a real DeepSeek run", async ({ page }) => {
  await page.goto("/?view=builder");
  await page.locator(".builder-form").getByRole("textbox", { name: /^Name/ }).fill(`DeepSeek Memory ${Date.now()}`);
  await page.locator(".builder-form").getByRole("textbox", { name: /^Prompt/ }).fill("Use relevant durable memory facts and answer concisely.");
  await selectDeepSeek(page);
  await page.getByLabel("Enable Calculator").uncheck();
  await page.getByRole("button", { name: "Save agent" }).click();

  await page.getByLabel("Message").fill("Remember that my project codename is aurora-salt.");
  await page.getByRole("button", { name: "Run agent" }).click();
  await expect(page.getByText("Memory written", { exact: true })).toBeVisible({ timeout: 60_000 });
  await page.getByLabel("Message").fill("What is my project codename?");
  await page.getByRole("button", { name: "Run agent" }).click();
  await expect(page.getByText("Memory retrieved", { exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".chat-message.agent .agent-answer p").last()).toContainText("aurora-salt");

  const runId = new URL(page.url()).searchParams.get("run");
  expect(runId).not.toBeNull();
  const eventsResponse = await page.request.get(`/api/runs/${runId}/events`);
  expect(eventsResponse.ok()).toBe(true);
  const events = (await eventsResponse.json()) as Array<{ type: string }>;
  expect(events.map((event) => event.type)).toContain("memory.retrieved");
});
