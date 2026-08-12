import { expect, test } from "@playwright/test";

test("creates a mock calculator agent and persists its observable run", async ({ page }) => {
  await page.goto(process.env.AGENT_STUDIO_E2E_BASE_URL ?? "/");
  await expect(page.getByRole("heading", { name: "Build agents you can actually inspect." })).toBeVisible();

  await page.getByRole("button", { name: "创建 Agent" }).click();
  await page.getByLabel("Name").fill(`Calculator Agent ${Date.now()}`);
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
