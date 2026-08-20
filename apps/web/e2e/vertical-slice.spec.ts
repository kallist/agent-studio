import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

interface BrowserDiagnostics {
  consoleMessages: string[];
  pageErrors: string[];
  failedRequests: string[];
  successfulNoContentRequests: string[];
}

const diagnostics = new WeakMap<Page, BrowserDiagnostics>();

test.beforeEach(async ({ page }) => {
  const current: BrowserDiagnostics = {
    consoleMessages: [],
    pageErrors: [],
    failedRequests: [],
    successfulNoContentRequests: [],
  };
  diagnostics.set(page, current);
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      current.consoleMessages.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => current.pageErrors.push(error.message));
  page.on("requestfailed", (request) => {
    current.failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText ?? "unknown failure"}`);
  });
  page.on("response", (response) => {
    if (response.status() === 204) {
      current.successfulNoContentRequests.push(`${response.request().method()} ${response.url()}`);
    }
  });
  await page.addInitScript(() => window.localStorage.clear());
});

test.afterEach(async ({ page }, testInfo) => {
  const current = diagnostics.get(page);
  expect(current, "browser diagnostics should be installed").toBeDefined();
  if (!current) return;

  const intentionalOffline = testInfo.title.includes("real API offline state");
  const intentionalFiveHundred = testInfo.title.includes("structured backend 5xx");
  const intentionalProviderUnavailable = testInfo.title.includes("provider configuration error");
  const unexpectedConsole = current.consoleMessages.filter((message) => {
    if (intentionalOffline && message.includes("ERR_FAILED")) return false;
    if (intentionalFiveHundred && /500|Internal Server Error/.test(message)) return false;
    if (intentionalProviderUnavailable && /503|Service Unavailable/.test(message)) return false;
    return true;
  });
  const unexpectedFailedRequests = current.failedRequests.filter((request) => {
    if (request.includes("/stream?after_sequence=")) return false;
    if (intentionalOffline && request.includes("/api/")) return false;
    if (current.successfulNoContentRequests.some((successful) => request.startsWith(successful))) return false;
    return true;
  });

  expect(current.pageErrors, "unexpected pageerror events").toEqual([]);
  expect(unexpectedConsole, "unexpected console.error or console.warn messages").toEqual([]);
  expect(unexpectedFailedRequests, "unintended failed network requests").toEqual([]);
});

test("navigates Studio, builds a calculator agent, and inspects its persisted trace", async ({ page }) => {
  const name = `Portfolio Calculator ${Date.now()}`;
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  const workspaceMetrics = page.getByLabel("Workspace metrics");
  await expect(workspaceMetrics).toBeVisible();
  const dashboardResponse = await page.request.get("/api/observability/dashboard");
  expect(dashboardResponse.ok()).toBe(true);
  const dashboard = (await dashboardResponse.json()) as {
    total_runs: number;
    completed: number;
    failed: number;
    cancelled: number;
    success_rate: number | null;
    average_duration_ms: number | null;
  };
  await expect(workspaceMetrics.locator("article", { hasText: "Total runs" })).toContainText(String(dashboard.total_runs));
  await expect(workspaceMetrics.locator("article", { hasText: "Cancelled" })).toContainText(String(dashboard.cancelled));
  await expect(workspaceMetrics.locator("article", { hasText: "Success rate" })).toContainText(
    dashboard.success_rate === null ? "No completed or failed runs" : `${Math.round(dashboard.success_rate * 100)}%`,
  );
  await expect(workspaceMetrics.locator("article", { hasText: "Average duration" })).toContainText(
    dashboard.average_duration_ms === null ? "Awaiting recent terminal runs" : `${Math.round(dashboard.average_duration_ms)} ms`,
  );

  const agentsNavigation = page.getByRole("button", { name: "Agents", exact: true });
  await agentsNavigation.focus();
  await expect(agentsNavigation).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Agents", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Agent Builder", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Agent Builder" })).toBeVisible();
  await expect(page.getByLabel("Enable Durable Memory")).toBeChecked();
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
  const metrics = page.getByLabel("Observability metrics");
  await expect(metrics).toContainText("Duration");
  await expect(metrics).toContainText("Steps2");
  await expect(metrics).toContainText("Tool Calls1");
  await expect(metrics).toContainText("Token UsageN/A");
  await expect(page.getByRole("heading", { name: "User Input" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "LLM", exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tool Call" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tool Result" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Final", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Lifecycle", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Run Started" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tool Call" })).toBeHidden();
  await page.getByRole("button", { name: "Runtime / LLM", exact: true }).click();
  await expect(page.getByRole("heading", { name: "LLM", exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Tools", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Tool Call" })).toBeVisible();
  await expect(page.getByText("Calculator", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".latency").first()).toContainText("ms");
  await page.getByRole("button", { name: "Knowledge / RAG", exact: true }).click();
  await expect(page.getByText("No events match this filter.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Memory", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Memory Retrieval Skipped" })).toBeVisible();
  await page.getByRole("button", { name: "Errors", exact: true }).click();
  await expect(page.getByText("No events match this filter.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "All", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Tool Call" })).toBeVisible();

  await page.getByRole("button", { name: "Back to Playground" }).click();
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Clear this conversation?" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Clear conversation" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Clear this conversation?" })).toBeHidden();
  await expect(page.getByRole("button", { name: "Clear", exact: true })).toBeFocused();
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
  await page.getByRole("button", { name: "Knowledge / RAG", exact: true }).click();
  await expect(page.locator(".execution-timeline")).toContainText("result_count");
  await expect(page.locator(".execution-timeline")).toContainText("algorithm");
  await expect(page.locator(".execution-timeline").locator(".latency").first()).toContainText("ms");
  await expect(page.locator(".execution-timeline").getByText(/upload:\/\/security_policy\.txt/).first()).toBeVisible();
  await page.getByRole("button", { name: "All", exact: true }).click();
});

test("combines durable memory with knowledge search across deterministic runs", async ({ page }) => {
  const suffix = Date.now();
  const baseName = `Memory RAG ${suffix}`;
  await page.goto("/?view=builder");
  await page.getByLabel("Knowledge base name").fill(baseName);
  await page.getByLabel("Description").fill("Memory and retrieval integration evidence");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByRole("button", { name: new RegExp(baseName) })).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles(path.resolve(process.cwd(), "../../tests/fixtures/rag/security_policy.txt"));
  await page.getByRole("button", { name: "Upload & ingest" }).click();
  await expect(page.getByText("completed", { exact: true })).toBeVisible();

  await page.getByRole("checkbox", { name: new RegExp(baseName) }).check();
  await expect(page.getByLabel("Enable Durable Memory")).toBeChecked();
  await page.locator(".builder-form").getByRole("textbox", { name: /^Name/ }).fill(`Memory Knowledge Agent ${suffix}`);
  await page.locator(".builder-form").getByRole("textbox", { name: /^Prompt/ }).fill("Use relevant durable memory and attached knowledge.");
  await page.getByRole("button", { name: "Save agent" }).click();

  await page.getByLabel("Message").fill("Remember that project codename is Atlas.");
  await page.getByRole("button", { name: "Run agent" }).click();
  await expect(page.getByText("Memory written", { exact: true })).toBeVisible();
  await expect(page.getByText("Knowledge", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("project codename is Atlas", { exact: true })).toBeVisible();

  await page.getByLabel("Message").fill("Remember that project codename is Atlas and parser failures must be isolated.");
  await page.getByRole("button", { name: "Run agent" }).click();
  await expect(page.getByText("Memory retrieved", { exact: true })).toBeVisible();
  const citation = page.locator(".trace-citations").getByText(/security_policy\.txt · score/).first();
  await expect(citation).toBeVisible();
  await citation.click();
  await expect(page.locator(".trace-citations").getByText(/upload:\/\/security_policy\.txt/).first()).toBeVisible();
  await expect(page.locator(".chat-message.agent .agent-answer p")).toHaveText(/\S/);
  await expect(page.locator(".trace-panel").getByText("Final answer", { exact: true })).toBeVisible();
  await page.locator(".trace-panel").getByRole("button", { name: "Memory", exact: true }).click();
  await expect(page.locator(".trace-panel").getByText("Memory retrieved", { exact: true })).toBeVisible();
  await page.locator(".trace-panel").getByRole("button", { name: "All", exact: true }).click();

  const runId = new URL(page.url()).searchParams.get("run");
  expect(runId).not.toBeNull();
  const runResponse = await page.request.get(`/api/runs/${runId}`);
  expect(runResponse.ok()).toBe(true);
  const completedRun = (await runResponse.json()) as { status: string; output: string | null };
  expect(completedRun.status).toBe("completed");
  expect(completedRun.output?.trim()).toBeTruthy();

  const eventsResponse = await page.request.get(`/api/runs/${runId}/events`);
  expect(eventsResponse.ok()).toBe(true);
  const completedEvents = (await eventsResponse.json()) as Array<{ type: string; payload: Record<string, unknown> }>;
  const eventTypes = completedEvents.map((event) => event.type);
  expect(eventTypes).toContain("memory.retrieved");
  expect(eventTypes).toContain("llm.completed");
  expect(eventTypes).toContain("run.completed");
  const selectedIndex = completedEvents.findIndex(
    (event) => event.type === "tool.selected" && event.payload.tool === "knowledge_search",
  );
  const startedIndex = completedEvents.findIndex(
    (event) => event.type === "tool.started" && event.payload.tool === "knowledge_search",
  );
  const completedIndex = completedEvents.findIndex(
    (event) => event.type === "tool.completed" && event.payload.tool === "knowledge_search",
  );
  const finalLlmIndex = eventTypes.findIndex(
    (type, index) => type === "llm.completed" && index > completedIndex,
  );
  const runCompletedIndex = eventTypes.indexOf("run.completed");
  expect(selectedIndex).toBeGreaterThan(eventTypes.indexOf("memory.retrieved"));
  expect(startedIndex).toBeGreaterThan(selectedIndex);
  expect(completedIndex).toBeGreaterThan(startedIndex);
  expect(finalLlmIndex).toBeGreaterThan(completedIndex);
  expect(runCompletedIndex).toBeGreaterThan(finalLlmIndex);
  expect(String(completedEvents[runCompletedIndex]?.payload.final_output ?? "").trim()).not.toBe("");
  await expect(citation).toBeVisible();
  const deleteMemoryResponse = page.waitForResponse(
    (response) => response.request().method() === "DELETE" && response.url().includes("/memories/"),
  );
  await page.getByRole("button", { name: /Delete memory: project codename is Atlas/ }).click();
  expect((await deleteMemoryResponse).ok()).toBe(true);
  await expect(page.getByText("Memory deleted", { exact: true })).toBeVisible();
  await page.getByRole("checkbox", { name: /On|Off/ }).uncheck();
  await expect(page.getByText("Memory disabled", { exact: true })).toBeVisible();
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

test("observes failed and cancelled runs as distinct terminal states", async ({ page }) => {
  await page.goto("/?view=builder");
  await page.locator(".builder-form").getByRole("textbox", { name: /^Name/ }).fill(`Failure Cancellation ${Date.now()}`);
  await page.getByRole("button", { name: "Save agent" }).click();

  await page.getByLabel("Message").fill("Calculate 1 / 0");
  await page.getByRole("button", { name: "Run agent" }).click();
  await expect(page.locator(".chat-message.agent").getByText("Run failed", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Run detail", exact: true }).click();
  await expect(page.getByLabel("Observability metrics")).toContainText("Tool Failures1");
  await expect(page.getByText("tool_error", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Errors", exact: true }).click();
  await expect(page.getByText("tool_error", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "All", exact: true }).click();

  await page.getByRole("button", { name: "Back to Playground" }).click();
  await page.getByLabel("Message").fill("__playwright_wait_for_cancel__");
  await page.getByRole("button", { name: "Run agent" }).click();
  await page.getByRole("button", { name: "Cancel run", exact: true }).click();
  await expect(page.locator(".chat-message.agent").getByText("Run cancelled", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Run detail", exact: true }).click();
  await expect(page.getByLabel("Observability metrics")).toContainText("Cancelled");
  await expect(page.getByText("cancelled", { exact: true }).last()).toBeVisible();
});

test("renders an unknown generic SSE event once", async ({ page }) => {
  await page.addInitScript(() => {
    class FakeEventSource extends EventTarget {
      onopen: ((event: Event) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;

      constructor(url: string | URL) {
        super();
        window.setTimeout(() => {
          this.onopen?.(new Event("open"));
          const runId = String(url).match(/\/runs\/([^/]+)\/stream/)?.[1];
          if (!runId) return;
          const event = {
            event_id: "00000000-0000-0000-0000-000000000077",
            run_id: runId,
            sequence: 77,
            type: "policy.checked",
            timestamp: "2026-08-20T00:00:00Z",
            payload: { policy: "safe" },
          };
          const message = () => new MessageEvent("agent.event", { data: JSON.stringify(event) });
          this.dispatchEvent(message());
          this.dispatchEvent(message());
        });
      }

      close() {}
    }
    Object.defineProperty(window, "EventSource", { value: FakeEventSource });
  });

  await page.goto("/?view=builder");
  await page.locator(".builder-form").getByRole("textbox", { name: /^Name/ }).fill(`Future Event ${Date.now()}`);
  await page.getByRole("button", { name: "Save agent" }).click();
  await page.getByLabel("Message").fill("Show an unknown event.");
  await page.getByRole("button", { name: "Run agent" }).click();

  const genericEvent = page.locator(".trace-panel").getByText("policy.checked", { exact: true });
  await expect(genericEvent).toBeVisible();
  await expect(genericEvent).toHaveCount(1);
  await expect(page.locator(".trace-panel")).toContainText('"policy": "safe"');
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
  await page.getByRole("button", { name: "Agent Builder", exact: true }).click();
  await page.locator(".builder-form").getByRole("textbox", { name: /^Name/ }).fill(`Mobile Trace ${Date.now()}`);
  await page.getByRole("button", { name: "Save agent" }).click();
  await page.getByLabel("Message").fill("Remember that mobile validation is complete.");
  await page.getByRole("button", { name: "Run agent" }).click();
  await expect(page.getByText("Memory written", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Run detail", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Execution timeline" })).toBeVisible();
  await expect(page.getByLabel("Observability metrics")).toBeVisible();
  await expect(page.getByLabel("Trace filters")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Memory Written" })).toBeVisible();
  await expect(page.locator(".execution-timeline li article").first()).toBeVisible();
  await page.getByRole("button", { name: "Memory", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Memory Written" })).toBeVisible();
  await page.getByRole("button", { name: "All", exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("reports a real API offline state", async ({ page }) => {
  await page.route("**/api/**", (route) => route.abort());
  await page.goto("/");
  await expect(page.getByText("API offline", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".error-banner")).toContainText("Cannot connect to the Agent Studio API");
});

test("marks a structured backend 5xx unhealthy and recovers after a successful response", async ({ page }) => {
  let backendHealthy = false;
  await page.route("**/api/**", async (route) => {
    if (!backendHealthy) {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Internal Server Error" }),
      });
      return;
    }
    await route.continue();
  });

  await page.goto("/");
  const connectionPill = page.locator(".connection-pill");
  await expect(connectionPill).toHaveClass(/connection-offline/);
  await expect(connectionPill).toContainText("API offline");
  await expect(connectionPill).not.toContainText("Connected");
  await expect(page.locator(".environment-card")).toHaveClass(/connection-offline/);
  await expect(page.locator(".error-banner")).toContainText("Internal Server Error");

  backendHealthy = true;
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(connectionPill).toHaveClass(/connection-connected/);
  await expect(connectionPill).toContainText("Connected");
  await expect(page.locator(".error-banner")).toBeHidden();
});
