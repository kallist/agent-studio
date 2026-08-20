"use client";

import { Icon, type IconName } from "@/components/icons";
import { Button, EmptyState, PageHeader, StatusBadge, formatRelativeTime } from "@/components/ui";
import type { AgentDefinition, DashboardObservability } from "@/lib/api";
import type { RunSnapshot, StudioView } from "@/lib/studio-types";

export function Dashboard({ agents, telemetry, runs, loading, onNavigate, onInspectRun }: { agents: AgentDefinition[]; telemetry: DashboardObservability | null; runs: RunSnapshot[]; loading: boolean; onNavigate: (view: StudioView) => void; onInspectRun: (run: RunSnapshot) => void }) {
  const successRate = telemetry?.success_rate === null || telemetry?.success_rate === undefined ? "—" : `${Math.round(telemetry.success_rate * 100)}%`;
  const averageLatency = telemetry?.average_duration_ms === null || telemetry?.average_duration_ms === undefined ? "—" : `${Math.round(telemetry.average_duration_ms)} ms`;
  const metrics: Array<{ label: string; value: string | number; meta: string; icon: IconName; tone: string }> = [
    { label: "Agents", value: agents.length, meta: agents.length ? "Saved definitions" : "Create your first agent", icon: "agents", tone: "violet" },
    { label: "Total runs", value: telemetry?.total_runs ?? "—", meta: "Persisted backend runs", icon: "runs", tone: "blue" },
    { label: "Success rate", value: successRate, meta: telemetry && telemetry.completed + telemetry.failed ? `${telemetry.completed} completed · ${telemetry.failed} failed` : "No completed or failed runs", icon: "check", tone: "green" },
    { label: "Average duration", value: averageLatency, meta: telemetry?.average_duration_ms === null ? "Awaiting recent terminal runs" : "Most recent 30 runs", icon: "clock", tone: "amber" },
    { label: "Cancelled", value: telemetry?.cancelled ?? "—", meta: telemetry ? "Separate from failed" : "Awaiting telemetry", icon: "close", tone: "cyan" },
  ];
  return (
    <>
      <PageHeader eyebrow="Overview" title="Dashboard" description="A persisted view of real Agent Studio runs and measured telemetry." action={<Button icon="plus" onClick={() => onNavigate("builder")}>Create agent</Button>} />
      <section className="metric-grid" aria-label="Workspace metrics">
        {metrics.map((metric) => <article className={`metric-card ${loading ? "loading" : ""}`} key={metric.label}><div><p>{metric.label}</p>{loading ? <><span className="metric-value-skeleton" /><span className="metric-meta-skeleton" /></> : <><strong>{metric.value}</strong><small>{metric.meta}</small></>}</div><span className={`metric-icon ${metric.tone}`}><Icon name={metric.icon} /></span></article>)}
      </section>
      <section className="surface recent-runs">
        <div className="section-heading"><div><h2>Recent runs</h2><p>Real executions loaded from backend persistence.</p></div><Button variant="ghost" icon="arrow" onClick={() => runs[0] && onInspectRun(runs[0])} disabled={!runs.length}>View latest</Button></div>
        {runs.length === 0 ? <EmptyState icon="runs" title="No runs yet" description="Open the Playground and execute an agent. Metrics and trace links will appear here." action={<Button variant="secondary" icon="play" onClick={() => onNavigate(agents.length ? "playground" : "builder")}>{agents.length ? "Open Playground" : "Build an agent"}</Button>} /> : (
          <div className="table-wrap"><table><thead><tr><th>Run</th><th>Agent</th><th>Status</th><th>Tool calls</th><th>Duration</th><th>Started</th><th><span className="sr-only">Action</span></th></tr></thead><tbody>{runs.slice(0, 6).map((run) => <tr key={run.run_id}><td><button className="run-link" onClick={() => onInspectRun(run)}>{run.run_id.slice(0, 8)}</button></td><td><strong>{run.agentName}</strong></td><td><StatusBadge status={run.status} /></td><td>{run.tool_calls.total}</td><td>{run.duration_ms === null ? "—" : `${Math.round(run.duration_ms)} ms`}</td><td>{formatRelativeTime(run.created_at)}</td><td><button className="icon-button" aria-label={`Inspect run ${run.run_id.slice(0, 8)}`} onClick={() => onInspectRun(run)}><Icon name="chevron" /></button></td></tr>)}</tbody></table></div>
        )}
      </section>
    </>
  );
}
