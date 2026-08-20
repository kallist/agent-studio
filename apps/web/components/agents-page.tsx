"use client";

import { Icon } from "@/components/icons";
import { Button, EmptyState, LoadingSkeleton, PageHeader, StatusBadge, formatRelativeTime } from "@/components/ui";
import type { AgentDefinition, KnowledgeBase } from "@/lib/api";
import type { RunSnapshot } from "@/lib/studio-types";

export function AgentsPage({ agents, knowledgeBases, runs, loading, selectedId, onCreate, onOpen }: { agents: AgentDefinition[]; knowledgeBases: KnowledgeBase[]; runs: RunSnapshot[]; loading: boolean; selectedId: string | null; onCreate: () => void; onOpen: (agent: AgentDefinition) => void }) {
  return (
    <>
      <PageHeader eyebrow="Definitions" title="Agents" description="Versioned configurations connected to the real Agent Studio runtime." action={<Button icon="plus" onClick={onCreate}>New agent</Button>} />
      {loading ? <div className="agent-card-grid"><LoadingSkeleton rows={4} /></div> : agents.length === 0 ? <section className="surface"><EmptyState icon="agents" title="No agent definitions" description="Create a definition with a prompt and at least one enabled tool to unlock the Playground." action={<Button icon="builder" onClick={onCreate}>Open Agent Builder</Button>} /></section> : (
        <section className="agent-card-grid" aria-label="Agent definitions">
          {agents.map((agent) => {
            const lastRun = runs.find((run) => run.agent_id === agent.id);
            const boundKnowledge = agent.knowledge_base_ids.map((id) => knowledgeBases.find((base) => base.id === id)?.name ?? id.slice(0, 8));
            return <article key={agent.id} className={agent.id === selectedId ? "agent-definition-card selected" : "agent-definition-card"}>
              <div className="agent-card-top"><span className="agent-avatar"><Icon name="spark" /></span><StatusBadge status={agent.runtime_mode === "mock" ? "ready" : "needs-key"} /></div>
              <div className="agent-card-copy"><h2>{agent.name}</h2><p>{agent.instructions}</p></div>
              <dl className="agent-metadata"><div><dt>Tools</dt><dd>{agent.tools.length ? agent.tools.map((tool) => <span className="tool-chip" key={tool}><Icon name={tool === "calculator" ? "calculator" : tool === "knowledge_search" ? "knowledge" : "tool"} />{tool}</span>) : <span className="muted-value">None</span>}</dd></div><div><dt>Knowledge base</dt><dd>{boundKnowledge.length ? boundKnowledge.map((name) => <span className="tool-chip" key={name}><Icon name="knowledge" />{name}</span>) : <span className="muted-value"><Icon name="knowledge" />Not bound</span>}</dd></div><div><dt>Memory</dt><dd><span className="muted-value"><Icon name="memory" />{agent.memory_enabled ? "Enabled" : "Disabled"}</span></dd></div><div><dt>Last run</dt><dd>{lastRun ? <><StatusBadge status={lastRun.status} /><span className="meta-time">{formatRelativeTime(lastRun.terminal_at ?? lastRun.created_at)}</span></> : <span className="muted-value">Never</span>}</dd></div></dl>
              <div className="agent-card-footer"><span>{agent.runtime_mode === "mock" ? "Deterministic mock" : agent.model ?? "Provider model"}</span><Button variant="secondary" icon="play" onClick={() => onOpen(agent)}>Open in Playground</Button></div>
            </article>;
          })}
        </section>
      )}
    </>
  );
}
