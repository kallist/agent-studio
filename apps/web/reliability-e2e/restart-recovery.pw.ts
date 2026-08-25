import { expect, test } from "@playwright/test";

test("reconnects the real UI to persisted data after Web restart", async ({ page }) => {
  const pageErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("requestfailed", (request) => {
    failedRequests.push(`${request.method()} ${request.url()}`);
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByLabel("Workspace metrics")).toBeVisible();
  await page.getByRole("button", { name: "Agents", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Agents", exact: true })).toBeVisible();
  await expect(
    page.getByText("Task 13 Reliability Calculator", { exact: true })
  ).toBeVisible();

  expect(pageErrors).toEqual([]);
  expect(failedRequests.filter((request) => !request.includes("/stream"))).toEqual([]);
});
