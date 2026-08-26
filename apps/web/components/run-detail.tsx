"use client";

import { useState } from "react";

import { Icon, type IconName } from "@/components/icons";
import { filterTraceEvents, TraceFilterBar, toolMeta, type TraceFilter } from "@/components/trace-timeline";
import { Button, EmptyState, PageHeader, StatusBadge } from "@/components/ui";
import { displayTermination } from "@/i18n/display";
import { useI18n, type Translate, type TranslationKey } from "@/i18n/provider";
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

const detailMeta: Record<KnownEventType, { label: TranslationKey; category: TranslationKey; icon: IconName; tone: string }> = {
  "run.started": { label: "runs.runStartedEvent", category: "trace.system", icon: "play", tone: "input" },
  "step.started": { label: "runs.stepStartedEvent", category: "trace.runtimeCategory", icon: "terminal", tone: "model" },
  "llm.started": { label: "runs.llmEvent", category: "runs.modelRequest", icon: "spark", tone: "model" },
  "llm.retrying": { label: "runs.llmRetryEvent", category: "runs.modelRetry", icon: "refresh", tone: "model" },
  "llm.completed": { label: "runs.llmEvent", category: "runs.modelResponse", icon: "spark", tone: "model" },
  "tool.selected": { label: "runs.toolSelectedEvent", category: "trace.routing", icon: "tool", tone: "tool" },
  "tool.started": { label: "runs.toolCallEvent", category: "trace.tool", icon: "tool", tone: "tool" },
  "tool.completed": { label: "runs.toolResultEvent", category: "trace.tool", icon: "check", tone: "tool" },
  "tool.failed": { label: "runs.toolResultEvent", category: "runs.failed", icon: "error", tone: "failed" },
  "step.completed": { label: "runs.stepCompletedEvent", category: "trace.runtimeCategory", icon: "check", tone: "model" },
  "memory.retrieved": { label: "runs.memoryRetrievedEvent", category: "trace.memory", icon: "memory", tone: "memory" },
  "memory.retrieval.skipped": { label: "runs.memorySkippedEvent", category: "trace.memory", icon: "memory", tone: "memory" },
  "memory.written": { label: "runs.memoryWrittenEvent", category: "trace.memory", icon: "memory", tone: "memory" },
  "run.completed": { label: "runs.final", category: "trace.output", icon: "check", tone: "final" },
  "run.failed": { label: "runs.final", category: "runs.failed", icon: "error", tone: "failed" },
  "run.cancelled": { label: "runs.runCancelledEvent", category: "trace.system", icon: "close", tone: "failed" },
};

function eventDetail(event: AgentEvent, t: Translate): string {
  const payload = event.payload;
  if (typeof payload.result === "string") return payload.result;
  if (payload.result && typeof payload.result === "object") return JSON.stringify(payload.result, null, 2);
  if (typeof payload.final_output === "string") return payload.final_output;
  if (typeof payload.error === "string") return payload.error;
  if (typeof payload.summary === "string") return payload.summary;
  if (payload.arguments && typeof payload.arguments === "object") return JSON.stringify(payload.arguments, null, 2);
  const remaining = Object.fromEntries(Object.entries(payload).filter(([key]) => key !== "tool" && key !== "latency_ms"));
  return Object.keys(remaining).length ? JSON.stringify(remaining, null, 2) : t("trace.eventRecorded");
}

function eventCitations(event: AgentEvent): Array<Record<string, unknown>> {
  if (Array.isArray(event.payload.citations)) return event.payload.citations as Array<Record<string, unknown>>;
  const result = event.payload.result;
  if (result && typeof result === "object" && "results" in result && Array.isArray((result as Record<string, unknown>).results)) {
    return (result as { results: Array<Record<string, unknown>> }).results;
  }
  return [];
}

function toSteps(run: RunResult, events: AgentEvent[], t: Translate): DetailStep[] {
  const steps: DetailStep[] = [{ id: "input", label: t("runs.userInput"), category: t("runs.input"), icon: "playground", detail: run.input, timestamp: run.created_at, tone: "input", citations: [] }];
  for (const event of events) {
    const toolName = typeof event.payload.tool === "string" ? event.payload.tool : null;
    const tool = toolName ? toolMeta(toolName, t) : null;
    const translated = detailMeta[event.type as KnownEventType];
    const base = translated ? { ...translated, label: t(translated.label), category: t(translated.category) } : { label: event.type, category: t("runs.unknownEvent"), icon: "terminal" as IconName, tone: "model" };
    const isToolEvent = event.type.startsWith("tool.") && tool;
    steps.push({
      id: event.event_id,
      ...base,
      category: isToolEvent ? tool.label : base.category,
      icon: isToolEvent ? tool.icon : base.icon,
      tone: isToolEvent ? tool.tone : base.tone,
      detail: eventDetail(event, t),
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
  const { locale, t } = useI18n();
  const [filter, setFilter] = useState<TraceFilter>("all");
  if (!run) return <><PageHeader eyebrow={t("runs.eyebrow")} title={t("runs.title")} description={t("runs.descriptionEmpty")} /><section className="surface"><EmptyState icon="runs" title={t("runs.noRunTitle")} description={t("runs.noRunDescription")} action={<Button icon="play" onClick={onBack}>{t("runs.openPlayground")}</Button>} /></section></>;
  const visibleEvents = filterTraceEvents(events, filter);
  const steps = toSteps(run, visibleEvents, t);
  const duration = observability?.duration_ms;
  const usage = observability?.usage;
  const displayMetric = (value: number | null | undefined) => value == null ? t("common.values.notAvailable") : value;
  return (
    <>
      <PageHeader eyebrow={t("runs.eyebrow")} title={t("runs.title")} description={t("runs.description", { id: run.id.slice(0, 8), name: agent?.name ?? t("dashboard.recent.agent") })} action={<div className="button-row"><Button variant="secondary" icon={run.run_kind === "evaluation" ? "evaluation" : "playground"} onClick={onBack}>{run.run_kind === "evaluation" ? t("runs.backEvaluations") : t("runs.backPlayground")}</Button>{run.run_kind === "normal" && <Button icon="refresh" onClick={onRerun} disabled={run.status === "pending" || run.status === "running"}>{t("runs.runAgain")}</Button>}</div>} />
      <section className="run-summary-grid observability-summary" aria-label={t("runs.metrics")}><article className="run-summary-primary"><div><span>{t("runs.runId")}</span><code>{run.id}</code></div><StatusBadge status={run.status} /></article><article><span>{t("runs.duration")}</span><strong>{duration == null ? t("common.values.notAvailable") : `${Math.round(duration)} ms`}</strong></article><article><span>{t("runs.steps")}</span><strong>{observability?.step_count ?? t("common.values.notAvailable")}</strong></article><article><span>{t("runs.events")}</span><strong>{observability?.event_count ?? events.length}</strong></article><article><span>{t("runs.toolCalls")}</span><strong>{observability?.tool_calls.total ?? t("common.values.notAvailable")}</strong></article><article><span>{t("runs.toolFailures")}</span><strong>{observability?.tool_calls.failed ?? t("common.values.notAvailable")}</strong></article><article><span>{t("runs.providerRequests")}</span><strong>{displayMetric(usage?.requests)}</strong></article><article><span>{t("runs.inputTokens")}</span><strong>{displayMetric(usage?.input_tokens)}</strong></article><article><span>{t("runs.outputTokens")}</span><strong>{displayMetric(usage?.output_tokens)}</strong></article><article><span>{t("runs.totalTokens")}</span><strong>{displayMetric(usage?.total_tokens)}</strong></article></section>
      <div className="run-detail-layout">
        <section className="surface execution-timeline"><div className="section-heading"><div><h2>{t("runs.timeline")}</h2><p>{t("runs.timelineDescription")}</p></div><span className="trace-count">{t("common.counts.events", { count: visibleEvents.length })}</span></div><TraceFilterBar value={filter} onChange={setFilter} />{visibleEvents.length === 0 ? <div className="trace-filter-empty light">{t("trace.noMatch")}</div> : <ol aria-label={t("runs.timelineAria")}>{steps.map((step) => <li key={step.id} className={`detail-step tone-${step.tone}`}><div className="detail-rail"><span><Icon name={step.icon} /></span></div><article><header><div><small>{step.category}</small><h3>{step.label}</h3></div><time dateTime={step.timestamp}>{new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(step.timestamp))}</time></header><pre>{step.detail}</pre><dl className="event-correlation">{step.stepIndex != null && <div><dt>{t("trace.step")}</dt><dd>{step.stepIndex}</dd></div>}{step.toolCallId && <div><dt>{t("trace.toolCall")}</dt><dd><code>{step.toolCallId}</code></dd></div>}</dl>{step.citations.length > 0 && <div className="trace-citations">{step.citations.map((citation, index) => <details key={String(citation.chunk_id ?? index)}><summary>[{index + 1}] {String(citation.document ?? t("trace.source"))} · {t("trace.score")} {Number(citation.score ?? 0).toFixed(3)}</summary><dl><div><dt>{t("trace.source")}</dt><dd>{String(citation.source ?? t("common.values.unknown"))}</dd></div><div><dt>{t("trace.document")}</dt><dd>{String(citation.document_id ?? citation.document ?? t("common.values.unknown"))}</dd></div><div><dt>{t("trace.chunk")}</dt><dd>#{String(citation.chunk_index ?? "—")} · {String(citation.chunk_id ?? t("common.values.unknown"))}</dd></div><div><dt>{t("trace.metadata")}</dt><dd><code>{JSON.stringify(citation.metadata ?? {})}</code></dd></div></dl></details>)}</div>}{step.meta && <span className="latency"><Icon name="clock" />{step.meta}</span>}</article></li>)}</ol>}</section>
        <aside className="run-inspector"><section className="surface"><h2>{t("runs.metadataTitle")}</h2><dl><div><dt>{t("runs.status")}</dt><dd><StatusBadge status={run.status} /></dd></div><div><dt>{t("runs.runtime")}</dt><dd>{observability?.runtime_type ?? agent?.runtime_mode ?? "—"}</dd></div><div><dt>{t("runs.provider")}</dt><dd>{observability?.provider_type ?? t("common.values.notAvailable")}</dd></div><div><dt>{t("runs.apiStyle")}</dt><dd>{observability?.api_style ?? t("common.values.notAvailable")}</dd></div><div><dt>{t("runs.model")}</dt><dd>{observability?.model ?? agent?.model ?? t("common.values.notAvailable")}</dd></div><div><dt>{t("runs.termination")}</dt><dd>{displayTermination(t, observability?.termination_reason)}</dd></div><div><dt>{t("runs.started")}</dt><dd>{observability?.started_at ? new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "medium" }).format(new Date(observability.started_at)) : t("common.values.notAvailable")}</dd></div><div><dt>{t("runs.completed")}</dt><dd>{observability?.terminal_at ? new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "medium" }).format(new Date(observability.terminal_at)) : t("common.values.notAvailable")}</dd></div></dl></section>{run.output && <section className="surface final-output"><span><Icon name="check" /></span><div><h2>{t("runs.finalOutput")}</h2><p>{run.output}</p></div></section>}{run.error && <section className="surface final-output failed"><span><Icon name="error" /></span><div><h2>{t("runs.error")}</h2><p>{observability?.error_summary ?? run.error}</p></div></section>}</aside>
      </div>
    </>
  );
}
