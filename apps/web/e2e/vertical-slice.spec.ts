import { expect, test } from "@playwright/test";
import path from "node:path";

test("creates a mock calculator agent and persists its observable run", async ({ page }) => {
  await page.goto(process.env.AGENT_STUDIO_E2E_BASE_URL ?? "/");
  await expect(page.getByRole("heading", { name: "Build agents you can actually inspect." })).toBeVisible();

  await page.getByRole("button", { name: "创建 Agent" }).click();
  await page.getByLabel("Name", { exact: true }).fill(`Calculator Agent ${Date.now()}`);
  await page.getByLabel("Instructions").fill("Use the calculator tool for exact arithmetic.");
  await page.getByLabel("Runtime mode").selectOption("mock");
  await page.getByRole("button", { name: "保存 Agent" }).click();

  await expect(page.getByText("Deterministic demo · no API key")).toBeVisible();
  await page.getByLabel("Message").fill("计算 128 * 37 + 456");
  await page.getByRole("button", { name: "Run agent →" }).click();

  await expect(page.getByText("5192").first()).toBeVisible();
  await expect(page.getByText("Tool selected")).toBeVisible();
  await expect(page.getByText("Tool input")).toBeVisible();
  await expect(page.getByText("Tool result")).toBeVisible();
  await expect(page.getByText("Final answer")).toBeVisible();

  await page.reload();
  await expect(page.getByText("5192").first()).toBeVisible();
  await expect(page.getByText("Tool result")).toBeVisible();
});

test("ingests knowledge, retrieves a cited chunk, and exposes agent sources", async ({ page }) => {
  const name = `Security handbook ${Date.now()}`;
  await page.goto("/");

  await page.getByLabel("Knowledge base name").fill(name);
  await page.getByLabel("Description").fill("Upload and parser security policies");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByRole("button", { name: new RegExp(name) })).toBeVisible();

  const fixture = path.resolve(
    process.cwd(),
    "../../tests/fixtures/rag/security_policy.txt",
  );
  await page.locator('input[type="file"]').setInputFiles(fixture);
  await page.getByRole("button", { name: "Upload & ingest" }).click();
  await expect(page.getByText("completed", { exact: true })).toBeVisible();

  await page.getByLabel("Test retrieval").fill("How are path traversal and parser failures handled?");
  await page.getByRole("button", { name: "Semantic + keyword search" }).click();
  await expect(page.getByText("security_policy.txt", { exact: false })).toBeVisible();
  await expect(page.getByText(/path traversal/i)).toBeVisible();
  await expect(page.getByText(/score/i)).toBeVisible();

  await page.getByRole("button", { name: "创建 Agent" }).click();
  await page.getByLabel("Name", { exact: true }).fill(`Grounded Agent ${Date.now()}`);
  await page.getByLabel("Instructions").fill("Answer only from attached knowledge.");
  await page.locator('form.create-card select[name="knowledge_base_id"]').selectOption({ label: name });
  await expect(page.getByText("✓ knowledge_search")).toBeVisible();
  await page.getByRole("button", { name: "保存 Agent" }).click();

  await page.getByLabel("Message").fill("How are parser failures isolated?");
  await page.getByRole("button", { name: "Run agent →" }).click();
  const traceCitation = page.locator(".trace-citations").getByText(/security_policy\.txt · score/);
  await expect(traceCitation).toBeVisible();
  await traceCitation.click();
  await expect(
    page.locator(".trace-citations").getByText(/upload:\/\/security_policy\.txt/),
  ).toBeVisible();
});
