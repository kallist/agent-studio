import path from "node:path";

import { expect, test } from "@playwright/test";

const onlineEnabled = process.env.RUN_REAL_OPENAI_TESTS === "1";
const keyConfigured = Boolean(process.env.OPENAI_API_KEY?.trim());
const model = process.env.OPENAI_REAL_TEST_MODEL?.trim();

test.skip(!onlineEnabled, "Real OpenAI E2E requires RUN_REAL_OPENAI_TESTS=1.");
test.skip(!keyConfigured, "Real OpenAI: BLOCKED — OPENAI_API_KEY not configured");
test.skip(!model, "Real OpenAI E2E requires explicit OPENAI_REAL_TEST_MODEL.");
test.describe.configure({ mode: "serial" });
test.setTimeout(120_000);

test("runs a streamed real OpenAI basic response and renders provider usage", async ({ page }) => {
  await page.goto("/?view=builder");
  await expect(page.getByRole("heading", { name: "Agent Builder" })).toBeVisible();
  await page.locator(".builder-form").getByRole("textbox", { name: /^Name/ }).fill(`Real OpenAI ${Date.now()}`);
  await page.locator(".builder-form").getByRole("textbox", { name: /^Prompt/ }).fill("Reply with exactly REAL_OPENAI_OK and nothing else.");
  await page.getByRole("radio", { name: /OpenAI/ }).check();
  await page.getByLabel("Model").fill(model!);
  await page.getByLabel("Enable Calculator").uncheck();
  await page.getByLabel("Enable Durable Memory").uncheck();
  await page.getByRole("button", { name: "Save agent" }).click();

  await expect(page.getByText("Agent saved", { exact: true })).toBeVisible();
  await page.getByLabel("Message").fill("Return the validation token now.");
  await page.getByRole("button", { name: "Run agent" }).click();
  await expect(page.getByText("REAL_OPENAI_OK", { exact: true }).first()).toBeVisible({ timeout: 60_000 });

  await page.getByRole("button", { name: "Run detail", exact: true }).click();
  const metrics = page.getByLabel("Observability metrics");
  await expect(metrics).toContainText("Provider Requests1");
  await expect(metrics).not.toContainText("Total TokensN/A");
  const inspector = page.locator(".run-inspector");
  await expect(inspector).toContainText("Provideropenai");
  await expect(inspector).toContainText(`Model${model!}`);
});

test("runs a true OpenAI calculator tool call through the application executor", async ({ page }) => {
  await page.goto("/?view=builder");
  await page.locator(".builder-form").getByRole("textbox", { name: /^Name/ }).fill(`Real Calculator ${Date.now()}`);
  await page.locator(".builder-form").getByRole("textbox", { name: /^Prompt/ }).fill("For arithmetic, call calculator exactly once and then return only its exact result.");
  await page.getByRole("radio", { name: /OpenAI/ }).check();
  await page.getByLabel("Model").fill(model!);
  await page.getByLabel("Enable Durable Memory").uncheck();
  await page.getByRole("button", { name: "Save agent" }).click();

  await page.getByLabel("Message").fill("Calculate 128 * 37 + 456.");
  await page.getByRole("button", { name: "Run agent" }).click();
  await expect(page.locator(".chat-message.agent .agent-answer p").last()).toContainText("5192", { timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "Tool Call" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tool Result" })).toBeVisible();

  await page.getByRole("button", { name: "Run detail", exact: true }).click();
  const metrics = page.getByLabel("Observability metrics");
  await expect(metrics).toContainText("Tool Calls1");
  await expect(metrics).toContainText("Provider Requests2");
  await expect(metrics).not.toContainText("Total TokensN/A");
  await expect(page.locator(".execution-timeline")).toContainText("5192");
});

test("runs real OpenAI with application-owned RAG and citations", async ({ page }) => {
  const baseName = `Real OpenAI RAG ${Date.now()}`;
  await page.goto("/?view=builder");
  await page.getByLabel("Knowledge base name").fill(baseName);
  await page.getByLabel("Description").fill("Bounded online RAG validation");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByRole("button", { name: new RegExp(baseName) })).toBeVisible();

  const fixture = path.resolve(process.cwd(), "../../tests/fixtures/rag/security_policy.txt");
  await page.locator('input[type="file"]').setInputFiles(fixture);
  await page.getByRole("button", { name: "Upload & ingest" }).click();
  await expect(page.getByText("completed", { exact: true })).toBeVisible();
  await page.getByRole("checkbox", { name: new RegExp(baseName) }).check();

  await page.locator(".builder-form").getByRole("textbox", { name: /^Name/ }).fill(`Real RAG Agent ${Date.now()}`);
  await page.locator(".builder-form").getByRole("textbox", { name: /^Prompt/ }).fill("For knowledge questions, call knowledge_search exactly once and answer from its cited result.");
  await page.getByRole("radio", { name: /OpenAI/ }).check();
  await page.getByLabel("Model").fill(model!);
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

test("retrieves durable Memory for a real OpenAI run", async ({ page }) => {
  await page.goto("/?view=builder");
  await page.locator(".builder-form").getByRole("textbox", { name: /^Name/ }).fill(`Real Memory ${Date.now()}`);
  await page.locator(".builder-form").getByRole("textbox", { name: /^Prompt/ }).fill("Use relevant durable memory facts and answer concisely.");
  await page.getByRole("radio", { name: /OpenAI/ }).check();
  await page.getByLabel("Model").fill(model!);
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
