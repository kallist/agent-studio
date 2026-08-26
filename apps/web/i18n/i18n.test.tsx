import { fireEvent, render, screen, waitFor } from "@/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { displayStatus } from "@/i18n/display";
import { DEFAULT_LOCALE, LOCALE_COOKIE, normalizeLocale } from "@/i18n/config";
import { en } from "@/i18n/messages/en";
import { zhCN } from "@/i18n/messages/zh-CN";
import { createTranslator, interpolate, useI18n, type TranslationKey } from "@/i18n/provider";
import { Playground } from "@/components/playground";
import { api, type AgentDefinition, type AgentEvent, type RunResult } from "@/lib/api";

function flatten(value: object, prefix = ""): string[] {
  return Object.entries(value).flatMap(([key, nested]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof nested === "string" ? [path] : flatten(nested as object, path);
  });
}

function Probe() {
  const { locale, setLocale, t } = useI18n();
  return <><span>{locale}</span><h1>{t("dashboard.title")}</h1><button onClick={() => setLocale(locale === "en" ? "zh-CN" : "en")}>{t("language.label")}</button></>;
}

const agent: AgentDefinition = {
  id: "agent-1", name: "My Chinese Agent", instructions: "Explain in English.", runtime_mode: "deepseek", model: "deepseek-v4-flash", tools: [], knowledge_base_ids: [], memory_enabled: false, created_at: "2026-08-26T00:00:00Z",
};

const completedRun: RunResult = {
  id: "run-1", agent_id: agent.id, status: "completed", run_kind: "normal", input: "Explain PostgreSQL in English.", output: "PostgreSQL is an open-source database.", error: null, created_at: "2026-08-26T00:00:00Z", updated_at: "2026-08-26T00:00:01Z",
};

function RequestProbe() {
  const { locale, setLocale } = useI18n();
  return <><button onClick={() => setLocale(locale === "en" ? "zh-CN" : "en")}>locale</button><button onClick={() => void api.createRun(agent.id, completedRun.input)}>request</button></>;
}

describe("i18n", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.cookie = `${LOCALE_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
    document.documentElement.lang = "en";
    vi.unstubAllGlobals();
  });

  it("defaults invalid persisted values to English", () => {
    expect(DEFAULT_LOCALE).toBe("en");
    expect(normalizeLocale(undefined)).toBe("en");
    expect(normalizeLocale("nonsense")).toBe("en");
  });

  it("switches immediately to Chinese, persists, and switches back", () => {
    render(<Probe />);
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Change language" }));
    expect(screen.getByRole("heading", { name: "仪表盘" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(document.cookie).toContain(`${LOCALE_COOKIE}=zh-CN`);
    fireEvent.click(screen.getByRole("button", { name: "切换语言" }));
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en");
  });

  it("keeps the session locale active when cookie persistence is unavailable", () => {
    vi.spyOn(document, "cookie", "set").mockImplementation(() => {
      throw new Error("cookie blocked");
    });
    render(<Probe />);
    expect(() => fireEvent.click(screen.getByRole("button", { name: "Change language" }))).not.toThrow();
    expect(screen.getByRole("heading", { name: "仪表盘" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("zh-CN");
  });

  it("restores a persisted preference when the provider remounts", () => {
    const firstRender = render(<Probe />);
    fireEvent.click(screen.getByRole("button", { name: "Change language" }));
    const persisted = document.cookie.match(new RegExp(`(?:^|; )${LOCALE_COOKIE}=([^;]+)`))?.[1];
    firstRender.unmount();
    render(<Probe />, { locale: normalizeLocale(persisted && decodeURIComponent(persisted)) });
    expect(screen.getByRole("heading", { name: "仪表盘" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("zh-CN");
  });

  it("keeps English and Chinese dictionary keys identical", () => {
    expect(flatten(zhCN).sort()).toEqual(flatten(en).sort());
  });

  it("interpolates variables without HTML execution", () => {
    expect(interpolate("Showing {count} runs for {name}", { count: 2, name: "<img>" })).toBe("Showing 2 runs for <img>");
  });

  it("falls back without rendering a raw missing key", () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const missing = "agents.missing" as TranslationKey;
    expect(createTranslator("zh-CN")(missing)).toBe(en.common.errors.generic);
    expect(console.warn).toHaveBeenCalledWith("Missing translation: zh-CN.agents.missing");
  });

  it("localizes enum display while preserving the canonical value", () => {
    const canonical = "completed";
    expect(displayStatus(createTranslator("en"), canonical)).toBe("Completed");
    expect(displayStatus(createTranslator("zh-CN"), canonical)).toBe("已完成");
    expect(canonical).toBe("completed");
  });

  it("preserves user data, provider/model IDs, output, and raw event types in Chinese UI", () => {
    const rawEvent: AgentEvent = { event_id: "event-1", run_id: completedRun.id, sequence: 1, type: "custom.raw.event", timestamp: completedRun.created_at, payload: { summary: "Raw event summary" } };
    render(<Playground agents={[agent]} selected={agent} run={completedRun} events={[rawEvent]} input={completedRun.input} submitting={false} onSelectAgent={vi.fn()} onInput={vi.fn()} onRun={vi.fn()} onCancel={vi.fn()} onBuild={vi.fn()} onInspect={vi.fn()} onRequestClear={vi.fn()} />, { locale: "zh-CN" });
    expect(screen.getAllByText(agent.name, { exact: true }).length).toBeGreaterThan(0);
    expect(screen.getByText(agent.model!, { exact: true })).toBeInTheDocument();
    expect(screen.getAllByText(completedRun.input, { exact: true }).length).toBeGreaterThan(0);
    expect(screen.getByText(completedRun.output!, { exact: true })).toBeInTheDocument();
    expect(screen.getByText(rawEvent.type, { exact: true })).toBeInTheDocument();
    expect(agent.runtime_mode).toBe("deepseek");
    expect(rawEvent.type).toBe("custom.raw.event");
  });

  it("does not add locale or language instructions to run request bodies", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(completedRun), { status: 202, headers: { "Content-Type": "application/json" } })));
    vi.stubGlobal("fetch", fetchMock);
    render(<RequestProbe />);
    fireEvent.click(screen.getByRole("button", { name: "request" }));
    fireEvent.click(screen.getByRole("button", { name: "locale" }));
    fireEvent.click(screen.getByRole("button", { name: "request" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const bodies = fetchMock.mock.calls.map((call) => JSON.parse(String((call[1] as RequestInit).body)) as Record<string, unknown>);
    expect(bodies).toEqual([{ input: completedRun.input }, { input: completedRun.input }]);
    expect(bodies.every((body) => !("locale" in body) && !("language" in body))).toBe(true);
  });
});
