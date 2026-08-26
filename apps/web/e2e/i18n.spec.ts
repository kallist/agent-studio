import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

async function createKnowledgeAgent(page: Page) {
  const suffix = Date.now().toString(36);
  const baseResponse = await page.request.post("/api/knowledge-bases", {
    data: { name: `I18N Knowledge ${suffix}`, description: "English RAG isolation fixture" },
  });
  expect(baseResponse.status()).toBe(201);
  const base = await baseResponse.json() as { id: string; name: string };
  const fixture = path.resolve(process.cwd(), "../../tests/fixtures/rag/security_policy.txt");
  const uploadResponse = await page.request.post(`/api/knowledge-bases/${base.id}/documents`, {
    multipart: { file: { name: "security_policy.txt", mimeType: "text/plain", buffer: readFileSync(fixture) } },
  });
  expect(uploadResponse.status()).toBe(202);
  const upload = await uploadResponse.json() as { ingestion_job: { id: string } };
  await expect.poll(async () => {
    const response = await page.request.get(`/api/ingestion-jobs/${upload.ingestion_job.id}`);
    return (await response.json() as { state: string }).state;
  }).toBe("completed");
  const agentResponse = await page.request.post("/api/agents", { data: {
    name: `English RAG Agent ${suffix}`,
    instructions: "Answer from the attached English knowledge without translating it.",
    runtime_mode: "mock",
    model: null,
    tools: ["knowledge_search"],
    knowledge_base_ids: [base.id],
    memory_enabled: false,
  } });
  expect(agentResponse.status()).toBe(201);
  const agent = await agentResponse.json() as { id: string; name: string };
  return { agent, base };
}

async function createMockRun(page: Page) {
  const suffix = Date.now().toString(36);
  const agentResponse = await page.request.post("/api/agents", {
    data: {
      name: `I18N Agent ${suffix}`,
      instructions: "Use the calculator tool for arithmetic and return the exact result.",
      runtime_mode: "mock",
      model: null,
      tools: ["calculator"],
      knowledge_base_ids: [],
      memory_enabled: true,
    },
  });
  expect(agentResponse.status()).toBe(201);
  const agent = await agentResponse.json() as { id: string; name: string };
  const runResponse = await page.request.post(`/api/agents/${agent.id}/runs`, { data: { input: "Calculate 128 * 37 + 456" } });
  expect(runResponse.status()).toBe(202);
  const run = await runResponse.json() as { id: string; status: string };
  await expect.poll(async () => {
    const response = await page.request.get(`/api/runs/${run.id}`);
    return (await response.json() as { status: string }).status;
  }).toBe("completed");
  return { agent, run };
}

function captureConsole(page: Page): string[] {
  const messages: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") messages.push(`${message.type()}: ${message.text()}`);
  });
  page.on("pageerror", (error) => messages.push(`pageerror: ${error.message}`));
  return messages;
}

test("switches all major Studio surfaces to Simplified Chinese and persists across reload", async ({ page }) => {
  const messages = captureConsole(page);
  const rag = await createKnowledgeAgent(page);
  const { agent } = await createMockRun(page);
  await page.goto("/");

  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page.getByRole("combobox", { name: "Change language" }).selectOption("zh-CN");
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await expect(page.getByRole("heading", { name: "仪表盘" })).toBeVisible();
  await expect(page.getByRole("button", { name: "智能体", exact: true })).toBeVisible();

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await expect(page.getByRole("heading", { name: "仪表盘" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "切换语言" })).toHaveValue("zh-CN");

  await page.getByRole("button", { name: "智能体", exact: true }).click();
  await expect(page.getByRole("heading", { name: "智能体", exact: true })).toBeVisible();
  await expect(page.getByText(agent.name, { exact: true }).first()).toBeVisible();

  await page.getByRole("button", { name: "智能体构建器", exact: true }).click();
  await expect(page.getByRole("heading", { name: "智能体构建器" })).toBeVisible();
  await expect(page.getByText("身份与行为", { exact: true })).toBeVisible();
  await expect(page.getByText("知识库 / RAG", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Mock", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: new RegExp(rag.base.name) }).click();
  const ragQuery = "How are parser failures and path traversal handled?";
  await page.getByLabel("测试检索").fill(ragQuery);
  const searchRequest = page.waitForRequest((request) => request.method() === "POST" && request.url().includes(`/knowledge-bases/${rag.base.id}/search`));
  await page.getByRole("button", { name: "语义 + 关键词搜索" }).click();
  expect((await searchRequest).postDataJSON()).toEqual({ query: ragQuery, top_k: 5, hybrid: true });
  await expect(page.getByText(/Parser errors fail only the ingestion job/).first()).toBeVisible();

  await page.getByRole("button", { name: /^调试台/ }).click();
  await expect(page.getByRole("heading", { name: "调试台" })).toBeVisible();
  await expect(page.getByRole("button", { name: "运行智能体" })).toBeVisible();
  await expect(page.getByPlaceholder("让智能体计算一些内容…")).toBeVisible();
  await expect(page.getByRole("heading", { name: "已记住的事实" })).toBeVisible();

  await page.getByRole("button", { name: "评测", exact: true }).click();
  await expect(page.getByRole("heading", { name: "评测", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "运行详情", exact: true }).click();
  await expect(page.getByRole("heading", { name: "运行详情", exact: true })).toBeVisible();
  await expect(page.getByText("运行 ID（Run ID）", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "全部" })).toBeVisible();
  await expect(page.getByText("5192", { exact: true }).first()).toBeVisible();

  await page.getByRole("button", { name: /^调试台/ }).click();
  await page.getByLabel("当前智能体").selectOption(rag.agent.id);
  await page.getByPlaceholder("让智能体计算一些内容…").fill(ragQuery);
  await page.getByRole("button", { name: "运行智能体" }).click();
  const citation = page.locator(".trace-citations").getByText(/security_policy\.txt · 得分/).first();
  await expect(citation).toBeVisible();
  await citation.click();
  await expect(page.locator(".trace-citations").getByText("upload://security_policy.txt", { exact: true }).first()).toBeVisible();
  const ragRunId = new URL(page.url()).searchParams.get("run");
  expect(ragRunId).not.toBeNull();
  const ragRun = await (await page.request.get(`/api/runs/${ragRunId}`)).json() as { input: string; output: string | null };
  expect(ragRun.input).toBe(ragQuery);
  expect(ragRun.output).not.toBeNull();
  const ragEvents = await (await page.request.get(`/api/runs/${ragRunId}/events`)).json() as Array<{ type: string; payload: Record<string, unknown> }>;
  const knowledgeEvent = ragEvents.find((event) => event.type === "tool.completed" && event.payload.tool === "knowledge_search");
  expect(knowledgeEvent?.payload.arguments).toEqual({ query: ragQuery, top_k: 5 });
  expect(JSON.stringify(knowledgeEvent?.payload.result)).toContain("upload://security_policy.txt");
  expect(JSON.stringify(knowledgeEvent?.payload.result)).not.toContain("content");

  expect(messages, "console warnings, hydration failures, or translation errors").toEqual([]);
});

test("invalid persisted locale falls back to English and switching back updates the cookie", async ({ context, page }) => {
  await context.addCookies([{ name: "agent-studio.locale", value: "nonsense", domain: "127.0.0.1", path: "/", sameSite: "Lax" }]);
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page.getByRole("combobox", { name: "Change language" }).selectOption("zh-CN");
  await page.getByRole("combobox", { name: "切换语言" }).selectOption("en");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  const cookie = (await context.cookies()).find((item) => item.name === "agent-studio.locale");
  expect(cookie?.value).toBe("en");
});

test("language switcher remains usable without horizontal overflow at 390x844", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const switcher = page.getByRole("combobox", { name: "Change language" });
  await expect(switcher).toBeVisible();
  await switcher.selectOption("zh-CN");
  await expect(page.getByRole("heading", { name: "仪表盘" })).toBeVisible();
  const box = await page.getByRole("combobox", { name: "切换语言" }).boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
