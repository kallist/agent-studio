"use client";

import { useState } from "react";

import { Icon, type IconName } from "@/components/icons";
import { filterTraceEvents, TraceFilterBar, toolMeta, type TraceFilter } from "@/components/trace-timeline";
import { Button, EmptyState, PageHeader, StatusBadge } from "@/components/ui";
import type { AgentDefinition, AgentEvent, KnownEventType, RunObservability, RunResult } from "@/lib/api";

interface DetailStep {
  id: string;
  label: string;
  category: string;
  icon: IconName;
  detail: string;
  timestamp: string;
  tone: string;
  meta?: string;
  stepIndex?: number;
  toolCallId?: string;
  citations: Array<Record<string, unknown>>;
}

const detailMeta: Record<KnownEventType, { label: string; category: string; icon: IconName; tone: string }> = {
  "run.started": { label: "Run Started", category: "System", icon: "play", tone: "input" },
  "step.started": { label: "Step Started", category: "Runtime", icon: "terminal", tone: "model" },
  "llm.started": { label: "LLM", category: "Model request", icon: "spark", tone: "model" },
  "llm.retrying": { label: "LLM Retry", category: "Model retry", icon: "refresh", tone: "model" },
  "llm.completed": { label: "LLM", category: "Model response", icon: "spark", tone: "model" },
  "tool.selected": { label: "Tool Selected", category: "Routing", icon: "tool", tone: "tool" },
  "tool.started": { label: "Tool Call", category: "Tool", icon: "tool", tone: "tool" },
  "tool.completed": { label: "Tool Result", category: "Tool", icon: "check", tone: "tool" },
  "tool.failed": { label: "Tool Result", category: "Failed", icon: "error", tone: "failed" },
  "step.completed": { label: "Step Completed", category: "Runtime", icon: "check", tone: "model" },
  "memory.retrieved": { label: "Memory Retrieved", category: "Memory", icon: "memory", tone: "memory" },
  "memory.retrieval.skipped": { label: "Memory Retrieval Skipped", category: "Memory", icon: "memory", tone: "memory" },
  "memory.written": { label: "Memory Written", category: "Memory", icon: "memory", tone: "memory" },
  "run.completed": { label: "Final", category: "Output", icon: "check", tone: "final" },
  "run.failed": { label: "Final", category: "Failed", icon: "error", tone: "failed" },
  "run.cancelled": { label: "Run Cancelled", category: "System", icon: "close", tone: "failed" },
};

function eventDetail(event: AgentEvent): string {
  const payload = event.payload;
  if (typeof payload.result === "string") return payload.result;
  if (payload.result && typeof payload.result === "object") return JSON.stringify(payload.result, null, 2);
  if (typeof payload.final_output === "string") return payload.final_output;
  if (typeof payload.error === "string") return payload.error;
  if (typeof payload.summary === "string") return payload.summary;
  if (payload.arguments && typeof payload.arguments === "object") return JSON.stringify(payload.arguments, null, 2);
  const remaining = Object.fromEntries(Object.entries(payload).filter(([key]) => key !== "tool" && key !== "latency_ms"));
  return Object.keys(remaining).length ? JSON.stringify(remaining, null, 2) : "Event recorded";
}

function eventCitations(event: AgentEvent): Array<Record<string, unknown>> {
  if (Array.isArray(event.payload.citations)) return event.payload.citations as Array<Record<string, unknown>>;
  const result = event.payload.result;
  if (result && typeof result === "object" && "results" in result && Array.isArray((result as Record<string, unknown>).results)) {
    return (result as { results: Array<Record<string, unknown>> }).results;
  }
  return [];
}

function toSteps(run: RunResult, events: AgentEvent[]): DetailStep[] {
  const steps: DetailStep[] = [{ id: "input", label: "User Input", category: "Input", icon: "playground", detail: run.input, timestamp: run.created_at, tone: "input", citations: [] }];
  for (const event of events) {
    const toolName = typeof event.payload.tool === "string" ? event.payload.tool : null;
    const tool = toolName ? toolMeta(toolName) : null;
    const base = detailMeta[event.type as KnownEventType] ?? { label: event.type, category: "Unknown event", icon: "terminal" as IconName, tone: "model" };
    const isToolEvent = event.type.startsWith("tool.") && tool;
    steps.push({
      id: event.event_id,
      ...base,
      category: isToolEvent ? tool.label : base.category,
      icon: isToolEvent ? tool.icon : base.icon,
      tone: isToolEvent ? tool.tone : base.tone,
      detail: eventDetail(event),
      timestamp: event.timestamp,
      meta: typeof (event.duration_ms ?? event.payload.latency_ms) === "number" ? `${String(event.duration_ms ?? event.payload.latency_ms)} ms` : undefined,
      stepIndex: typeof (event.step_index ?? event.payload.step) === "number" ? Number(event.step_index ?? event.payload.step) : undefined,
      toolCallId: typeof (event.tool_call_id ?? event.payload.call_id) === "string" ? String(event.tool_call_id ?? event.payload.call_id) : undefined,
      citations: eventCitations(event),
    });
  }
  return steps;
}

export function RunDetail({ run, events, observability, agent, onBack, onRerun }: { run: RunResult | null; events: AgentEvent[]; observability: RunObservability | null; agent: AgentDefinition | null; onBack: () => void; onRerun: () => void }) {
  const [filter, setFilter] = useState<TraceFilter>("all");
  if (!run) return <><PageHeader eyebrow="Trace explorer" title="Run Detail" description="Inspect an execution after it has been started in the Playground." /><section className="surface"><EmptyState icon="runs" title="No run selected" description="Execute an agent or choose a recent run from the Dashboard." action={<Button icon="play" onClick={onBack}>Open Playground</Button>} /></section></>;
  const visibleEvents = filterTraceEvents(events, filter);
  const steps = toSteps(run, visibleEvents);
  const duration = observability?.duration_ms;
  const usage = observability?.usage;
  const displayMetric = (value: number | null | undefined) => value == null ? "N/A" : value;
  return (
    <>
      <PageHeader eyebrow="Trace explorer" title="Run Detail" description={`Inspecting run ${run.id.slice(0, 8)} from ${agent?.name ?? "Agent"}.`} action={<div className="button-row"><Button variant="secondary" icon={run.run_kind === "evaluation" ? "evaluation" : "playground"} onClick={onBack}>{run.run_kind === "evaluation" ? "Back to Evaluations" : "Back to Playground"}</Button>{run.run_kind === "normal" && <Button icon="refresh" onClick={onRerun} disabled={run.status === "pending" || run.status === "running"}>Run again</Button>}</div>} />
      <section className="run-summary-grid observability-summary" aria-label="Observability metrics"><article className="run-summary-primary"><div><span>Run ID</span><code>{run.id}</code></div><StatusBadge status={run.status} /></article><article><span>Duration</span><strong>{duration == null ? "N/A" : `${Math.round(duration)} ms`}</strong></article><article><span>Steps</span><strong>{observability?.step_count ?? "N/A"}</strong></article><article><span>Events</span><strong>{observability?.event_count ?? events.length}</strong></article><article><span>Tool Calls</span><strong>{observability?.tool_calls.total ?? "N/A"}</strong></article><article><span>Tool Failures</span><strong>{observability?.tool_calls.failed ?? "N/A"}</strong></article><article><span>Provider Requests</span><strong>{displayMetric(usage?.requests)}</strong></article><article><span>Input Tokens</span><strong>{displayMetric(usage?.input_tokens)}</strong></article><article><span>Output Tokens</span><strong>{displayMetric(usage?.output_tokens)}</strong></article><article><span>Total Tokens</span><strong>{displayMetric(usage?.total_tokens)}</strong></article></section>
      <div className="run-detail-layout">
        <section className="surface execution-timeline"><div className="section-heading"><div><h2>Execution timeline</h2><p>Application-owned events in persisted order.</p></div><span className="trace-count">{visibleEvents.length} events</span></div><TraceFilterBar value={filter} onChange={setFilter} />{visibleEvents.length === 0 ? <div className="trace-filter-empty light">No events match this filter.</div> : <ol aria-label="Run execution timeline">{steps.map((step) => <li key={step.id} className={`detail-step tone-${step.tone}`}><div className="detail-rail"><span><Icon name={step.icon} /></span></div><article><header><div><small>{step.category}</small><h3>{step.label}</h3></div><time dateTime={step.timestamp}>{new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(step.timestamp))}</time></header><pre>{step.detail}</pre><dl className="event-correlation">{step.stepIndex != null && <div><dt>Step</dt><dd>{step.stepIndex}</dd></div>}{step.toolCallId && <div><dt>Tool call</dt><dd><code>{step.toolCallId}</code></dd></div>}</dl>{step.citations.length > 0 && <div className="trace-citations">{step.citations.map((citation, index) => <details key={String(citation.chunk_id ?? index)}><summary>[{index + 1}] {String(citation.document ?? "Source")} · score {Number(citation.score ?? 0).toFixed(3)}</summary><dl><div><dt>Source</dt><dd>{String(citation.source ?? "Unknown")}</dd></div><div><dt>Document</dt><dd>{String(citation.document_id ?? citation.document ?? "Unknown")}</dd></div><div><dt>Chunk</dt><dd>#{String(citation.chunk_index ?? "—")} · {String(citation.chunk_id ?? "Unknown")}</dd></div><div><dt>Metadata</dt><dd><code>{JSON.stringify(citation.metadata ?? {})}</code></dd></div></dl></details>)}</div>}{step.meta && <span className="latency"><Icon name="clock" />{step.meta}</span>}</article></li>)}</ol>}</section>
        <aside className="run-inspector"><section className="surface"><h2>Run metadata</h2><dl><div><dt>Status</dt><dd><StatusBadge status={run.status} /></dd></div><div><dt>Runtime</dt><dd>{observability?.runtime_type ?? agent?.runtime_mode ?? "—"}</dd></div><div><dt>Provider</dt><dd>{observability?.provider_type ?? "N/A"}</dd></div><div><dt>API style</dt><dd>{observability?.api_style ?? "N/A"}</dd></div><div><dt>Model</dt><dd>{observability?.model ?? agent?.model ?? "N/A"}</dd></div><div><dt>Termination</dt><dd>{observability?.termination_reason ?? "N/A"}</dd></div><div><dt>Started</dt><dd>{observability?.started_at ? new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "medium" }).format(new Date(observability.started_at)) : "N/A"}</dd></div><div><dt>Completed</dt><dd>{observability?.terminal_at ? new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "medium" }).format(new Date(observability.terminal_at)) : "N/A"}</dd></div></dl></section>{run.output && <section className="surface final-output"><span><Icon name="check" /></span><div><h2>Final output</h2><p>{run.output}</p></div></section>}{run.error && <section className="surface final-output failed"><span><Icon name="error" /></span><div><h2>Error</h2><p>{observability?.error_summary ?? run.error}</p></div></section>}</aside>
      </div>
    </>
  );
}
