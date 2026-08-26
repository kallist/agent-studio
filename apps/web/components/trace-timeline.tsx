"use client";

import { useState } from "react";

import { Icon, type IconName } from "@/components/icons";
import { useI18n, type Translate, type TranslationKey } from "@/i18n/provider";
import type { AgentEvent, KnownEventType } from "@/lib/api";

interface EventMeta { label: TranslationKey; category: TranslationKey; icon: IconName }

const eventMeta: Record<KnownEventType, EventMeta> = {
  "run.started": { label: "trace.runStarted", category: "trace.system", icon: "play" },
  "step.started": { label: "trace.stepStarted", category: "trace.runtimeCategory", icon: "terminal" },
  "llm.started": { label: "trace.llmRequest", category: "trace.model", icon: "spark" },
  "llm.retrying": { label: "trace.llmRetry", category: "trace.model", icon: "refresh" },
  "llm.completed": { label: "trace.llmResponse", category: "trace.model", icon: "spark" },
  "tool.selected": { label: "trace.toolSelected", category: "trace.routing", icon: "tool" },
  "tool.started": { label: "trace.toolCall", category: "trace.tool", icon: "tool" },
  "tool.completed": { label: "trace.toolResult", category: "trace.tool", icon: "check" },
  "tool.failed": { label: "trace.toolFailed", category: "trace.error", icon: "error" },
  "step.completed": { label: "trace.stepCompleted", category: "trace.runtimeCategory", icon: "check" },
  "memory.retrieved": { label: "trace.memoryRetrieved", category: "trace.memory", icon: "memory" },
  "memory.retrieval.skipped": { label: "trace.memorySkipped", category: "trace.memory", icon: "memory" },
  "memory.written": { label: "trace.memoryWritten", category: "trace.memory", icon: "memory" },
  "run.completed": { label: "trace.finalAnswer", category: "trace.output", icon: "check" },
  "run.failed": { label: "trace.runFailed", category: "trace.error", icon: "error" },
  "run.cancelled": { label: "trace.runCancelled", category: "trace.system", icon: "close" },
};

export type TraceFilter = "all" | "lifecycle" | "runtime" | "tools" | "knowledge" | "memory" | "errors";

const filters: Array<{ id: TraceFilter; label: TranslationKey }> = [
  { id: "all", label: "trace.all" }, { id: "lifecycle", label: "trace.lifecycle" }, { id: "runtime", label: "trace.runtime" }, { id: "tools", label: "trace.tools" }, { id: "knowledge", label: "trace.knowledge" }, { id: "memory", label: "trace.memory" }, { id: "errors", label: "trace.errors" },
];

function isKnowledgeEvent(event: AgentEvent): boolean {
  return typeof event.payload.tool === "string" && event.payload.tool === "knowledge_search";
}

export function filterTraceEvents(events: AgentEvent[], filter: TraceFilter): AgentEvent[] {
  if (filter === "all") return events;
  return events.filter((event) => {
    if (filter === "lifecycle") return event.type.startsWith("run.") || event.type.startsWith("step.");
    if (filter === "runtime") return event.type.startsWith("llm.");
    if (filter === "knowledge") return isKnowledgeEvent(event);
    if (filter === "tools") return event.type.startsWith("tool.") && !isKnowledgeEvent(event);
    if (filter === "memory") return event.type.startsWith("memory.");
    return event.type.includes("failed") || typeof event.payload.error === "string";
  });
}

export function TraceFilterBar({ value, onChange }: { value: TraceFilter; onChange: (filter: TraceFilter) => void }) {
  const { t } = useI18n();
  return (
    <div className="trace-filters" aria-label={t("trace.filtersLabel")}>
      {filters.map((filter) => <button key={filter.id} type="button" aria-pressed={value === filter.id} onClick={() => onChange(filter.id)}>{t(filter.label)}</button>)}
    </div>
  );
}

function metaFor(event: AgentEvent, t: Translate): { label: string; category: string; icon: IconName } {
  const meta = eventMeta[event.type as KnownEventType];
  return meta ? { label: t(meta.label), category: t(meta.category), icon: meta.icon } : { label: event.type, category: t("trace.event"), icon: "terminal" };
}

export function toolMeta(tool: string, t: Translate): { label: string; icon: IconName; tone: string } {
  const normalized = tool.toLowerCase();
  if (normalized.includes("calculator")) return { label: t("trace.calculator"), icon: "calculator", tone: "calculator" };
  if (normalized.includes("knowledge") || normalized.includes("search")) return { label: t("trace.knowledgeTool"), icon: "knowledge", tone: "knowledge" };
  if (normalized.includes("http") || normalized.includes("request")) return { label: "HTTP", icon: "http", tone: "http" };
  return { label: tool, icon: "tool", tone: "default" };
}

function detail(event: AgentEvent, t: Translate): string {
  const payload = event.payload;
  if (typeof payload.result === "string") return payload.result;
  if (payload.result && typeof payload.result === "object") {
    const result = payload.result as Record<string, unknown>;
    if (Array.isArray(result.results)) {
      return t(result.results.length === 1 ? "common.counts.retrievedChunksOne" : "common.counts.retrievedChunksOther", { count: result.results.length });
    }
    return JSON.stringify(payload.result, null, 2);
  }
  if (typeof payload.final_output === "string") return payload.final_output;
  if (typeof payload.error === "string") return payload.error;
  if (typeof payload.summary === "string") return payload.summary;
  if (payload.arguments && typeof payload.arguments === "object") return JSON.stringify(payload.arguments, null, 2);
  if (typeof payload.reason === "string") return payload.reason;
  if (typeof payload.runtime === "string") return `${payload.runtime} runtime`;
  const serializable = Object.fromEntries(Object.entries(payload).filter(([key]) => key !== "tool" && key !== "latency_ms"));
  return Object.keys(serializable).length ? JSON.stringify(serializable, null, 2) : t("trace.eventRecorded");
}

function citations(event: AgentEvent): Array<Record<string, unknown>> {
  if (Array.isArray(event.payload.citations)) return event.payload.citations as Array<Record<string, unknown>>;
  const result = event.payload.result;
  if (result && typeof result === "object" && "results" in result) {
    const nested = (result as Record<string, unknown>).results;
    if (Array.isArray(nested)) return nested as Array<Record<string, unknown>>;
  }
  return [];
}

function CitationList({ items }: { items: Array<Record<string, unknown>> }) {
  const { t } = useI18n();
  if (!items.length) return null;
  return (
    <div className="trace-citations" aria-label={t("trace.citations")}>
      {items.map((citation, index) => (
        <details key={String(citation.chunk_id ?? index)}>
          <summary>
            [{index + 1}] {String(citation.document ?? t("trace.source"))} · {t("trace.score")} {Number(citation.score ?? 0).toFixed(3)}
          </summary>
          <p>{String(citation.content ?? "")}</p>
          <dl>
            <div><dt>{t("trace.source")}</dt><dd>{String(citation.source ?? t("common.values.unknown"))}</dd></div>
            <div><dt>{t("trace.document")}</dt><dd>{String(citation.document_id ?? citation.document ?? t("common.values.unknown"))}</dd></div>
            <div><dt>{t("trace.chunk")}</dt><dd>#{String(citation.chunk_index ?? "—")} · {String(citation.chunk_id ?? t("common.values.unknown"))}</dd></div>
            {typeof citation.metadata === "object" && citation.metadata !== null && (
              <div><dt>{t("trace.metadata")}</dt><dd><code>{JSON.stringify(citation.metadata)}</code></dd></div>
            )}
          </dl>
        </details>
      ))}
    </div>
  );
}

export function TraceTimeline({ events }: { events: AgentEvent[] }) {
  const { t } = useI18n();
  const [filter, setFilter] = useState<TraceFilter>("all");
  const visibleEvents = filterTraceEvents(events, filter);
  if (events.length === 0) {
    return <div className="trace-empty"><span className="trace-empty-visual"><Icon name="terminal" /><i /><i /><i /></span><h3>{t("trace.emptyTitle")}</h3><p>{t("trace.emptyDescription")}</p></div>;
  }
  return (
    <>
      <TraceFilterBar value={filter} onChange={setFilter} />
      {visibleEvents.length === 0 ? <div className="trace-filter-empty">{t("trace.noMatch")}</div> : <ol className="trace-list" aria-label={t("trace.liveAria")}>
      {visibleEvents.map((event) => {
        const meta = metaFor(event, t);
        const tool = typeof event.payload.tool === "string" ? toolMeta(event.payload.tool, t) : null;
        const failed = event.type.includes("failed");
        const eventCitations = citations(event);
        return <li key={event.event_id} className={`trace-event ${failed ? "failed" : ""}`}>
          <div className="trace-rail"><span><Icon name={meta.icon} /></span></div>
          <article>
            <div className="trace-event-heading"><div><small>{meta.category}</small><strong>{meta.label}</strong></div><time dateTime={event.timestamp}>#{event.sequence}</time></div>
            {tool && <span className={`tool-type tool-${tool.tone}`}><Icon name={tool.icon} />{tool.label}</span>}
            <pre>{detail(event, t)}</pre>
            <CitationList items={eventCitations} />
            <dl className="trace-event-meta">
              {(event.step_index ?? event.payload.step) != null && <div><dt>{t("trace.step")}</dt><dd>{String(event.step_index ?? event.payload.step)}</dd></div>}
              {(event.tool_call_id ?? event.payload.call_id) != null && <div><dt>{t("trace.call")}</dt><dd><code>{String(event.tool_call_id ?? event.payload.call_id)}</code></dd></div>}
            </dl>
            {(event.duration_ms ?? event.payload.latency_ms) != null && <span className="latency"><Icon name="clock" />{String(event.duration_ms ?? event.payload.latency_ms)} ms</span>}
          </article>
        </li>;
      })}
      </ol>}
    </>
  );
}
