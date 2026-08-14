"use client";

import { Icon, type IconName } from "@/components/icons";
import { toolMeta } from "@/components/trace-timeline";
import { Button, EmptyState, PageHeader, StatusBadge } from "@/components/ui";
import type { AgentDefinition, AgentEvent, KnownEventType, RunResult } from "@/lib/api";

interface DetailStep {
  id: string;
  label: string;
  category: string;
  icon: IconName;
  detail: string;
  timestamp: string;
  tone: string;
  meta?: string;
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
      meta: typeof event.payload.latency_ms === "number" ? `${event.payload.latency_ms} ms` : undefined,
      citations: eventCitations(event),
    });
  }
  return steps;
}

export function RunDetail({ run, events, agent, onBack, onRerun }: { run: RunResult | null; events: AgentEvent[]; agent: AgentDefinition | null; onBack: () => void; onRerun: () => void }) {
  if (!run) return <><PageHeader eyebrow="Trace explorer" title="Run Detail" description="Inspect an execution after it has been started in the Playground." /><section className="surface"><EmptyState icon="runs" title="No run selected" description="Execute an agent or choose a recent run from the Dashboard." action={<Button icon="play" onClick={onBack}>Open Playground</Button>} /></section></>;
  const steps = toSteps(run, events);
  const duration = Math.max(0, new Date(run.updated_at).getTime() - new Date(run.created_at).getTime());
  return (
    <>
      <PageHeader eyebrow="Trace explorer" title="Run Detail" description={`Inspecting run ${run.id.slice(0, 8)} from ${agent?.name ?? "Agent"}.`} action={<div className="button-row"><Button variant="secondary" icon="playground" onClick={onBack}>Back to Playground</Button><Button icon="refresh" onClick={onRerun} disabled={run.status === "pending" || run.status === "running"}>Run again</Button></div>} />
      <section className="run-summary-grid"><article className="run-summary-primary"><div><span>Run ID</span><code>{run.id}</code></div><StatusBadge status={run.status} /></article><article><span>Agent</span><strong>{agent?.name ?? run.agent_id.slice(0, 8)}</strong></article><article><span>Duration</span><strong>{duration ? `${duration} ms` : "< 1 ms"}</strong></article><article><span>Events</span><strong>{events.length}</strong></article></section>
      <div className="run-detail-layout">
        <section className="surface execution-timeline"><div className="section-heading"><div><h2>Execution timeline</h2><p>Application-owned events in persisted order.</p></div><span className="trace-count">{steps.length} steps</span></div><ol aria-label="Run execution timeline">{steps.map((step) => <li key={step.id} className={`detail-step tone-${step.tone}`}><div className="detail-rail"><span><Icon name={step.icon} /></span></div><article><header><div><small>{step.category}</small><h3>{step.label}</h3></div><time dateTime={step.timestamp}>{new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(step.timestamp))}</time></header><pre>{step.detail}</pre>{step.citations.length > 0 && <div className="trace-citations">{step.citations.map((citation, index) => <details key={String(citation.chunk_id ?? index)}><summary>[{index + 1}] {String(citation.document ?? "Source")} · score {Number(citation.score ?? 0).toFixed(3)}</summary><p>{String(citation.content ?? "")}</p><dl><div><dt>Source</dt><dd>{String(citation.source ?? "Unknown")}</dd></div><div><dt>Document</dt><dd>{String(citation.document_id ?? citation.document ?? "Unknown")}</dd></div><div><dt>Chunk</dt><dd>#{String(citation.chunk_index ?? "—")} · {String(citation.chunk_id ?? "Unknown")}</dd></div><div><dt>Metadata</dt><dd><code>{JSON.stringify(citation.metadata ?? {})}</code></dd></div></dl></details>)}</div>}{step.meta && <span className="latency"><Icon name="clock" />{step.meta}</span>}</article></li>)}</ol></section>
        <aside className="run-inspector"><section className="surface"><h2>Run metadata</h2><dl><div><dt>Status</dt><dd><StatusBadge status={run.status} /></dd></div><div><dt>Runtime</dt><dd>{agent?.runtime_mode ?? "—"}</dd></div><div><dt>Model</dt><dd>{agent?.runtime_mode === "mock" ? "Deterministic mock" : agent?.model ?? "—"}</dd></div><div><dt>Started</dt><dd>{new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "medium" }).format(new Date(run.created_at))}</dd></div></dl></section>{run.output && <section className="surface final-output"><span><Icon name="check" /></span><div><h2>Final output</h2><p>{run.output}</p></div></section>}{run.error && <section className="surface final-output failed"><span><Icon name="error" /></span><div><h2>Error</h2><p>{run.error}</p></div></section>}</aside>
      </div>
    </>
  );
}
