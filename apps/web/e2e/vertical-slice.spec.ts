import { expect, test } from "@playwright/test";
import path from "node:path";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
});

test("navigates Studio, builds a calculator agent, and inspects its persisted trace", async ({ page }) => {
  const name = `Portfolio Calculator ${Date.now()}`;
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByLabel("Workspace metrics")).toBeVisible();

  const agentsNavigation = page.getByRole("button", { name: "Agents", exact: true });
  await agentsNavigation.focus();
  await expect(agentsNavigation).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Agents", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Agent Builder", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Agent Builder" })).toBeVisible();
  await expect(page.getByText("Available after the Durable Memory feature merges")).toBeVisible();
  await expect(page.getByRole("button", { name: "Unavailable" })).toBeDisabled();
  await expect(page.getByLabel("Max iterations")).toBeDisabled();

  await page.locator(".builder-form").getByRole("textbox", { name: /^Name/ }).fill(name);
  await page.locator(".builder-form").getByRole("textbox", { name: /^Prompt/ }).fill("Use the calculator tool for exact arithmetic.");
  await page.getByRole("button", { name: "Save agent" }).click();

  await expect(page.getByText("Agent saved", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Playground" })).toBeVisible();
  await page.getByLabel("Message").fill("Calculate 128 * 37 + 456");
  await page.getByRole("button", { name: "Run agent" }).click();

  await expect(page.getByText("5192", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Tool selected", { exact: true })).toBeVisible();
  await expect(page.getByText("Tool call", { exact: true })).toBeVisible();
  await expect(page.getByText("Tool result", { exact: true })).toBeVisible();
  await expect(page.getByText("Calculator", { exact: true }).first()).toBeVisible();

  await page.getByRole("button", { name: "Run detail", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Execution timeline" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "User Input" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "LLM", exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tool Call" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tool Result" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Final", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Back to Playground" }).click();
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Clear this conversation?" })).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByText("5192", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Dashboard", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Recent runs" })).toBeVisible();
  await expect(page.getByRole("cell", { name })).toBeVisible();
});

test("ingests knowledge, binds it to an agent, and preserves cited run metadata", async ({ page }) => {
  const baseName = `Security handbook ${Date.now()}`;
  await page.goto("/?view=builder");
  await expect(page.getByRole("heading", { name: "Agent Builder" })).toBeVisible();

  await page.getByLabel("Knowledge base name").fill(baseName);
  await page.getByLabel("Description").fill("Upload and parser security policies");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByRole("button", { name: new RegExp(baseName) })).toBeVisible();

  const fixture = path.resolve(process.cwd(), "../../tests/fixtures/rag/security_policy.txt");
  await page.locator('input[type="file"]').setInputFiles(fixture);
  await page.getByRole("button", { name: "Upload & ingest" }).click();
  await expect(page.getByText("completed", { exact: true })).toBeVisible();

  await page.getByLabel("Test retrieval").fill("How are path traversal and parser failures handled?");
  await page.getByRole("button", { name: "Semantic + keyword search" }).click();
  await expect(page.getByText("security_policy.txt", { exact: false }).first()).toBeVisible();
  await expect(page.getByText(/path traversal/i).first()).toBeVisible();
  await expect(page.getByText(/score/i).first()).toBeVisible();

  await page.getByRole("checkbox", { name: new RegExp(baseName) }).check();
  await expect(page.getByText("knowledge_search", { exact: true })).toBeVisible();
  await page.locator(".builder-form").getByRole("textbox", { name: /^Name/ }).fill(`Grounded Agent ${Date.now()}`);
  await page.locator(".builder-form").getByRole("textbox", { name: /^Prompt/ }).fill("Answer only from attached knowledge.");
  await page.getByRole("button", { name: "Save agent" }).click();

  await page.getByLabel("Message").fill("How are parser failures isolated?");
  await page.getByRole("button", { name: "Run agent" }).click();
  await expect(page.getByText("Knowledge", { exact: true }).first()).toBeVisible();
  const traceCitation = page.locator(".trace-citations").getByText(/security_policy\.txt · score/).first();
  await expect(traceCitation).toBeVisible();
  await traceCitation.click();
  await expect(page.locator(".trace-citations").getByText(/upload:\/\/security_policy\.txt/).first()).toBeVisible();
  await expect(page.locator(".trace-citations").getByText(/Metadata/).first()).toBeVisible();

  await page.getByRole("button", { name: "Run detail", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Execution timeline" })).toBeVisible();
  await expect(page.locator(".execution-timeline").getByText(/upload:\/\/security_policy\.txt/).first()).toBeVisible();
});

test("shows a real provider configuration error", async ({ page }) => {
  await page.goto("/?view=builder");
  await page.locator(".builder-form").getByRole("textbox", { name: /^Name/ }).fill(`OpenAI Error State ${Date.now()}`);
  await page.getByRole("radio", { name: /OpenAI/ }).check();
  await page.getByLabel("Model").fill("provider-model-id");
  await page.getByRole("button", { name: "Save agent" }).click();
  await page.getByLabel("Message").fill("Calculate 1 + 1");
  await page.getByRole("button", { name: "Run agent" }).click();
  await expect(page.locator(".error-banner")).toContainText("OpenAI provider is not configured");
  await expect(page.getByText("Run could not start", { exact: true })).toBeVisible();
});

test("keeps all primary views within a 390 by 844 viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  for (const view of ["Dashboard", "Agents", "Agent Builder", "Playground"] as const) {
    await page.getByRole("button", { name: view, exact: true }).click();
    await expect(page.getByRole("heading", { name: view, exact: true })).toBeVisible();
    if (view === "Agent Builder") await expect(page.getByLabel("Live agent preview")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  }
});
