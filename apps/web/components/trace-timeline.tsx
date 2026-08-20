"use client";

import { useState } from "react";

import { Icon, type IconName } from "@/components/icons";
import type { AgentEvent, KnownEventType } from "@/lib/api";

interface EventMeta { label: string; category: string; icon: IconName }

const eventMeta: Record<KnownEventType, EventMeta> = {
  "run.started": { label: "Run started", category: "System", icon: "play" },
  "step.started": { label: "Step started", category: "Runtime", icon: "terminal" },
  "llm.started": { label: "LLM request", category: "Model", icon: "spark" },
  "llm.retrying": { label: "LLM retry", category: "Model", icon: "refresh" },
  "llm.completed": { label: "LLM response", category: "Model", icon: "spark" },
  "tool.selected": { label: "Tool selected", category: "Routing", icon: "tool" },
  "tool.started": { label: "Tool call", category: "Tool", icon: "tool" },
  "tool.completed": { label: "Tool result", category: "Tool", icon: "check" },
  "tool.failed": { label: "Tool failed", category: "Error", icon: "error" },
  "step.completed": { label: "Step completed", category: "Runtime", icon: "check" },
  "memory.retrieved": { label: "Memory retrieved", category: "Memory", icon: "memory" },
  "memory.retrieval.skipped": { label: "Memory retrieval skipped", category: "Memory", icon: "memory" },
  "memory.written": { label: "Memory written", category: "Memory", icon: "memory" },
  "run.completed": { label: "Final answer", category: "Output", icon: "check" },
  "run.failed": { label: "Run failed", category: "Error", icon: "error" },
  "run.cancelled": { label: "Run cancelled", category: "System", icon: "close" },
};

export type TraceFilter = "all" | "lifecycle" | "runtime" | "tools" | "knowledge" | "memory" | "errors";

const filters: Array<{ id: TraceFilter; label: string }> = [
  { id: "all", label: "All" },
  { id: "lifecycle", label: "Lifecycle" },
  { id: "runtime", label: "Runtime / LLM" },
  { id: "tools", label: "Tools" },
  { id: "knowledge", label: "Knowledge / RAG" },
  { id: "memory", label: "Memory" },
  { id: "errors", label: "Errors" },
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
  return (
    <div className="trace-filters" aria-label="Trace filters">
      {filters.map((filter) => <button key={filter.id} type="button" aria-pressed={value === filter.id} onClick={() => onChange(filter.id)}>{filter.label}</button>)}
    </div>
  );
}

function metaFor(event: AgentEvent): EventMeta {
  return eventMeta[event.type as KnownEventType] ?? {
    label: event.type,
    category: "Event",
    icon: "terminal",
  };
}

export function toolMeta(tool: string): { label: string; icon: IconName; tone: string } {
  const normalized = tool.toLowerCase();
  if (normalized.includes("calculator")) return { label: "Calculator", icon: "calculator", tone: "calculator" };
  if (normalized.includes("knowledge") || normalized.includes("search")) return { label: "Knowledge", icon: "knowledge", tone: "knowledge" };
  if (normalized.includes("http") || normalized.includes("request")) return { label: "HTTP", icon: "http", tone: "http" };
  return { label: tool, icon: "tool", tone: "default" };
}

function detail(event: AgentEvent): string {
  const payload = event.payload;
  if (typeof payload.result === "string") return payload.result;
  if (payload.result && typeof payload.result === "object") {
    const result = payload.result as Record<string, unknown>;
    if (Array.isArray(result.results)) {
      return `Retrieved ${result.results.length} cited chunk${result.results.length === 1 ? "" : "s"}`;
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
  return Object.keys(serializable).length ? JSON.stringify(serializable, null, 2) : "Event recorded";
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
  if (!items.length) return null;
  return (
    <div className="trace-citations" aria-label="Knowledge citations">
      {items.map((citation, index) => (
        <details key={String(citation.chunk_id ?? index)}>
          <summary>
            [{index + 1}] {String(citation.document ?? "Source")} · score {Number(citation.score ?? 0).toFixed(3)}
          </summary>
          <p>{String(citation.content ?? "")}</p>
          <dl>
            <div><dt>Source</dt><dd>{String(citation.source ?? "Unknown")}</dd></div>
            <div><dt>Document</dt><dd>{String(citation.document_id ?? citation.document ?? "Unknown")}</dd></div>
            <div><dt>Chunk</dt><dd>#{String(citation.chunk_index ?? "—")} · {String(citation.chunk_id ?? "Unknown")}</dd></div>
            {typeof citation.metadata === "object" && citation.metadata !== null && (
              <div><dt>Metadata</dt><dd><code>{JSON.stringify(citation.metadata)}</code></dd></div>
            )}
          </dl>
        </details>
      ))}
    </div>
  );
}

export function TraceTimeline({ events }: { events: AgentEvent[] }) {
  const [filter, setFilter] = useState<TraceFilter>("all");
  const visibleEvents = filterTraceEvents(events, filter);
  if (events.length === 0) {
    return <div className="trace-empty"><span className="trace-empty-visual"><Icon name="terminal" /><i /><i /><i /></span><h3>Trace will appear here</h3><p>Each model step and tool call is streamed in execution order.</p></div>;
  }
  return (
    <>
      <TraceFilterBar value={filter} onChange={setFilter} />
      {visibleEvents.length === 0 ? <div className="trace-filter-empty">No events match this filter.</div> : <ol className="trace-list" aria-label="Live run trace">
      {visibleEvents.map((event) => {
        const meta = metaFor(event);
        const tool = typeof event.payload.tool === "string" ? toolMeta(event.payload.tool) : null;
        const failed = event.type.includes("failed");
        const eventCitations = citations(event);
        return <li key={event.event_id} className={`trace-event ${failed ? "failed" : ""}`}>
          <div className="trace-rail"><span><Icon name={meta.icon} /></span></div>
          <article>
            <div className="trace-event-heading"><div><small>{meta.category}</small><strong>{meta.label}</strong></div><time dateTime={event.timestamp}>#{event.sequence}</time></div>
            {tool && <span className={`tool-type tool-${tool.tone}`}><Icon name={tool.icon} />{tool.label}</span>}
            <pre>{detail(event)}</pre>
            <CitationList items={eventCitations} />
            <dl className="trace-event-meta">
              {(event.step_index ?? event.payload.step) != null && <div><dt>Step</dt><dd>{String(event.step_index ?? event.payload.step)}</dd></div>}
              {(event.tool_call_id ?? event.payload.call_id) != null && <div><dt>Call</dt><dd><code>{String(event.tool_call_id ?? event.payload.call_id)}</code></dd></div>}
            </dl>
            {(event.duration_ms ?? event.payload.latency_ms) != null && <span className="latency"><Icon name="clock" />{String(event.duration_ms ?? event.payload.latency_ms)} ms</span>}
          </article>
        </li>;
      })}
      </ol>}
    </>
  );
}
