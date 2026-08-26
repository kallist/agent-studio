"use client";

import { Icon } from "@/components/icons";
import { Button, EmptyState, LoadingSkeleton, PageHeader, StatusBadge, useRelativeTime } from "@/components/ui";
import { useI18n } from "@/i18n/provider";
import type { AgentDefinition, KnowledgeBase } from "@/lib/api";
import type { RunSnapshot } from "@/lib/studio-types";

export function AgentsPage({ agents, knowledgeBases, runs, loading, selectedId, onCreate, onOpen }: { agents: AgentDefinition[]; knowledgeBases: KnowledgeBase[]; runs: RunSnapshot[]; loading: boolean; selectedId: string | null; onCreate: () => void; onOpen: (agent: AgentDefinition) => void }) {
  const { t } = useI18n();
  const formatRelativeTime = useRelativeTime();
  return (
    <>
      <PageHeader eyebrow={t("agents.eyebrow")} title={t("agents.title")} description={t("agents.description")} action={<Button icon="plus" onClick={onCreate}>{t("agents.new")}</Button>} />
      {loading ? <div className="agent-card-grid"><LoadingSkeleton rows={4} /></div> : agents.length === 0 ? <section className="surface"><EmptyState icon="agents" title={t("agents.emptyTitle")} description={t("agents.emptyDescription")} action={<Button icon="builder" onClick={onCreate}>{t("agents.openBuilder")}</Button>} /></section> : (
        <section className="agent-card-grid" aria-label={t("agents.listLabel")}>
          {agents.map((agent) => {
            const lastRun = runs.find((run) => run.agent_id === agent.id);
            const boundKnowledge = agent.knowledge_base_ids.map((id) => knowledgeBases.find((base) => base.id === id)?.name ?? id.slice(0, 8));
            return <article key={agent.id} className={agent.id === selectedId ? "agent-definition-card selected" : "agent-definition-card"}>
              <div className="agent-card-top"><span className="agent-avatar"><Icon name="spark" /></span><StatusBadge status={agent.runtime_mode === "mock" ? "ready" : "needs-key"} /></div>
              <div className="agent-card-copy"><h2>{agent.name}</h2><p>{agent.instructions}</p></div>
              <dl className="agent-metadata"><div><dt>{t("agents.tools")}</dt><dd>{agent.tools.length ? agent.tools.map((tool) => <span className="tool-chip" key={tool}><Icon name={tool === "calculator" ? "calculator" : tool === "knowledge_search" ? "knowledge" : "tool"} />{tool}</span>) : <span className="muted-value">{t("common.values.none")}</span>}</dd></div><div><dt>{t("agents.knowledgeBase")}</dt><dd>{boundKnowledge.length ? boundKnowledge.map((name) => <span className="tool-chip" key={name}><Icon name="knowledge" />{name}</span>) : <span className="muted-value"><Icon name="knowledge" />{t("agents.knowledgeNotBound")}</span>}</dd></div><div><dt>{t("agents.memory")}</dt><dd><span className="muted-value"><Icon name="memory" />{agent.memory_enabled ? t("common.states.enabled") : t("common.states.disabled")}</span></dd></div><div><dt>{t("agents.lastRun")}</dt><dd>{lastRun ? <><StatusBadge status={lastRun.status} /><span className="meta-time">{formatRelativeTime(lastRun.terminal_at ?? lastRun.created_at)}</span></> : <span className="muted-value">{t("common.values.never")}</span>}</dd></div></dl>
              <div className="agent-card-footer"><span>{agent.runtime_mode === "mock" ? t("agents.deterministicMock") : agent.model ?? t("agents.providerModel")}</span><Button variant="secondary" icon="play" onClick={() => onOpen(agent)}>{t("agents.openPlayground")}</Button></div>
            </article>;
          })}
        </section>
      )}
    </>
  );
}
