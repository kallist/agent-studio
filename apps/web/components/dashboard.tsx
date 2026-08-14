"use client";

import { Icon, type IconName } from "@/components/icons";
import { Button, EmptyState, PageHeader, StatusBadge, formatRelativeTime } from "@/components/ui";
import type { AgentDefinition } from "@/lib/api";
import type { RunSnapshot, StudioView } from "@/lib/studio-types";

export function Dashboard({ agents, runs, loading, onNavigate, onInspectRun }: { agents: AgentDefinition[]; runs: RunSnapshot[]; loading: boolean; onNavigate: (view: StudioView) => void; onInspectRun: (run: RunSnapshot) => void }) {
  const today = new Date().toDateString();
  const runsToday = runs.filter((run) => new Date(run.created_at).toDateString() === today);
  const terminalRuns = runsToday.filter((run) => run.status === "completed" || run.status === "failed");
  const successRate = terminalRuns.length ? `${Math.round((terminalRuns.filter((run) => run.status === "completed").length / terminalRuns.length) * 100)}%` : "—";
  const latencies = runsToday.map((run) => run.latencyMs).filter((value): value is number => value !== null);
  const averageLatency = latencies.length ? `${Math.round(latencies.reduce((sum, value) => sum + value, 0) / latencies.length)} ms` : "—";
  const toolCalls = runsToday.reduce((sum, run) => sum + run.toolCalls, 0);
  const metrics: Array<{ label: string; value: string | number; meta: string; icon: IconName; tone: string }> = [
    { label: "Agents", value: agents.length, meta: agents.length ? "Saved definitions" : "Create your first agent", icon: "agents", tone: "violet" },
    { label: "Runs today", value: runsToday.length, meta: "Local workspace", icon: "runs", tone: "blue" },
    { label: "Success rate", value: successRate, meta: terminalRuns.length ? `${terminalRuns.length} terminal runs` : "No completed runs", icon: "check", tone: "green" },
    { label: "Average latency", value: averageLatency, meta: latencies.length ? "Measured tool time" : "Awaiting measurements", icon: "clock", tone: "amber" },
    { label: "Tool calls", value: toolCalls, meta: "Observed today", icon: "tool", tone: "cyan" },
  ];
  return (
    <>
      <PageHeader eyebrow="Overview" title="Dashboard" description="A live view of the agents and runs observed in this browser workspace." action={<Button icon="plus" onClick={() => onNavigate("builder")}>Create agent</Button>} />
      <section className="metric-grid" aria-label="Workspace metrics">
        {metrics.map((metric) => <article className={`metric-card ${loading ? "loading" : ""}`} key={metric.label}><div><p>{metric.label}</p>{loading ? <><span className="metric-value-skeleton" /><span className="metric-meta-skeleton" /></> : <><strong>{metric.value}</strong><small>{metric.meta}</small></>}</div><span className={`metric-icon ${metric.tone}`}><Icon name={metric.icon} /></span></article>)}
      </section>
      <section className="surface recent-runs">
        <div className="section-heading"><div><h2>Recent runs</h2><p>Real executions saved from this browser session.</p></div><Button variant="ghost" icon="arrow" onClick={() => runs[0] && onInspectRun(runs[0])} disabled={!runs.length}>View latest</Button></div>
        {runs.length === 0 ? <EmptyState icon="runs" title="No runs yet" description="Open the Playground and execute an agent. Metrics and trace links will appear here." action={<Button variant="secondary" icon="play" onClick={() => onNavigate(agents.length ? "playground" : "builder")}>{agents.length ? "Open Playground" : "Build an agent"}</Button>} /> : (
          <div className="table-wrap"><table><thead><tr><th>Run</th><th>Agent</th><th>Status</th><th>Tool calls</th><th>Latency</th><th>Started</th><th><span className="sr-only">Action</span></th></tr></thead><tbody>{runs.slice(0, 6).map((run) => <tr key={run.id}><td><button className="run-link" onClick={() => onInspectRun(run)}>{run.id.slice(0, 8)}</button></td><td><strong>{run.agentName}</strong></td><td><StatusBadge status={run.status} /></td><td>{run.toolCalls}</td><td>{run.latencyMs === null ? "—" : `${Math.round(run.latencyMs)} ms`}</td><td>{formatRelativeTime(run.created_at)}</td><td><button className="icon-button" aria-label={`Inspect run ${run.id.slice(0, 8)}`} onClick={() => onInspectRun(run)}><Icon name="chevron" /></button></td></tr>)}</tbody></table></div>
        )}
      </section>
    </>
  );
}
