"use client";

import { Icon, type IconName } from "@/components/icons";
import { Button, EmptyState, PageHeader, StatusBadge, useRelativeTime } from "@/components/ui";
import { useI18n } from "@/i18n/provider";
import type { AgentDefinition, DashboardObservability } from "@/lib/api";
import type { RunSnapshot, StudioView } from "@/lib/studio-types";

export function Dashboard({ agents, telemetry, runs, loading, onNavigate, onInspectRun }: { agents: AgentDefinition[]; telemetry: DashboardObservability | null; runs: RunSnapshot[]; loading: boolean; onNavigate: (view: StudioView) => void; onInspectRun: (run: RunSnapshot) => void }) {
  const { t } = useI18n();
  const formatRelativeTime = useRelativeTime();
  const successRate = telemetry?.success_rate === null || telemetry?.success_rate === undefined ? "—" : `${Math.round(telemetry.success_rate * 100)}%`;
  const averageLatency = telemetry?.average_duration_ms === null || telemetry?.average_duration_ms === undefined ? "—" : `${Math.round(telemetry.average_duration_ms)} ms`;
  const metrics: Array<{ label: string; value: string | number; meta: string; icon: IconName; tone: string }> = [
    { label: t("dashboard.metrics.agents"), value: agents.length, meta: agents.length ? t("dashboard.metrics.agentsSaved") : t("dashboard.metrics.agentsEmpty"), icon: "agents", tone: "violet" },
    { label: t("dashboard.metrics.totalRuns"), value: telemetry?.total_runs ?? "—", meta: t("dashboard.metrics.totalRunsMeta"), icon: "runs", tone: "blue" },
    { label: t("dashboard.metrics.successRate"), value: successRate, meta: telemetry && telemetry.completed + telemetry.failed ? t("dashboard.metrics.successMeta", { completed: telemetry.completed, failed: telemetry.failed }) : t("dashboard.metrics.successEmpty"), icon: "check", tone: "green" },
    { label: t("dashboard.metrics.averageDuration"), value: averageLatency, meta: telemetry?.average_duration_ms === null ? t("dashboard.metrics.averageAwaiting") : t("dashboard.metrics.averageRecent"), icon: "clock", tone: "amber" },
    { label: t("dashboard.metrics.cancelled"), value: telemetry?.cancelled ?? "—", meta: telemetry ? t("dashboard.metrics.cancelledMeta") : t("dashboard.metrics.cancelledAwaiting"), icon: "close", tone: "cyan" },
  ];
  return (
    <>
      <PageHeader eyebrow={t("dashboard.eyebrow")} title={t("dashboard.title")} description={t("dashboard.description")} action={<Button icon="plus" onClick={() => onNavigate("builder")}>{t("dashboard.createAgent")}</Button>} />
      <section className="metric-grid" aria-label={t("dashboard.metricsLabel")}>
        {metrics.map((metric) => <article className={`metric-card ${loading ? "loading" : ""}`} key={metric.label}><div><p>{metric.label}</p>{loading ? <><span className="metric-value-skeleton" /><span className="metric-meta-skeleton" /></> : <><strong>{metric.value}</strong><small>{metric.meta}</small></>}</div><span className={`metric-icon ${metric.tone}`}><Icon name={metric.icon} /></span></article>)}
      </section>
      <section className="surface recent-runs">
        <div className="section-heading"><div><h2>{t("dashboard.recent.title")}</h2><p>{t("dashboard.recent.description")}</p></div><Button variant="ghost" icon="arrow" onClick={() => runs[0] && onInspectRun(runs[0])} disabled={!runs.length}>{t("dashboard.recent.latest")}</Button></div>
        {runs.length === 0 ? <EmptyState icon="runs" title={t("dashboard.recent.emptyTitle")} description={t("dashboard.recent.emptyDescription")} action={<Button variant="secondary" icon="play" onClick={() => onNavigate(agents.length ? "playground" : "builder")}>{agents.length ? t("dashboard.recent.openPlayground") : t("dashboard.recent.buildAgent")}</Button>} /> : (
          <div className="table-wrap"><table><thead><tr><th>{t("dashboard.recent.run")}</th><th>{t("dashboard.recent.agent")}</th><th>{t("dashboard.recent.status")}</th><th>{t("dashboard.recent.toolCalls")}</th><th>{t("dashboard.recent.duration")}</th><th>{t("dashboard.recent.started")}</th><th><span className="sr-only">{t("dashboard.recent.action")}</span></th></tr></thead><tbody>{runs.slice(0, 6).map((run) => <tr key={run.run_id}><td><button className="run-link" onClick={() => onInspectRun(run)}>{run.run_id.slice(0, 8)}</button></td><td><strong>{run.agentName}</strong></td><td><StatusBadge status={run.status} /></td><td>{run.tool_calls.total}</td><td>{run.duration_ms === null ? "—" : `${Math.round(run.duration_ms)} ms`}</td><td>{formatRelativeTime(run.created_at)}</td><td><button className="icon-button" aria-label={t("dashboard.recent.inspect", { id: run.run_id.slice(0, 8) })} onClick={() => onInspectRun(run)}><Icon name="chevron" /></button></td></tr>)}</tbody></table></div>
        )}
      </section>
    </>
  );
}
