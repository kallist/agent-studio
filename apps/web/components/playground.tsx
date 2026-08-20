"use client";

import { FormEvent, KeyboardEvent } from "react";

import { Icon } from "@/components/icons";
import { TraceTimeline } from "@/components/trace-timeline";
import { Button, EmptyState, PageHeader, StatusBadge } from "@/components/ui";
import type { AgentDefinition, AgentEvent, RunResult } from "@/lib/api";

export function Playground({ agents, selected, run, events, input, submitting, onSelectAgent, onInput, onRun, onCancel, onBuild, onInspect, onRequestClear }: { agents: AgentDefinition[]; selected: AgentDefinition | null; run: RunResult | null; events: AgentEvent[]; input: string; submitting: boolean; onSelectAgent: (id: string) => void; onInput: (value: string) => void; onRun: (event: FormEvent<HTMLFormElement>) => void; onCancel: () => void; onBuild: () => void; onInspect: () => void; onRequestClear: () => void }) {
  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && input.trim() && !submitting) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };
  return (
    <>
      <PageHeader eyebrow="Execution workspace" title="Playground" description="Run a real agent and inspect normalized trace events as they stream." action={selected && <div className="agent-select-wrap"><label htmlFor="active-agent">Active agent</label><select id="active-agent" value={selected.id} onChange={(event) => onSelectAgent(event.target.value)}>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></div>} />
      {!selected ? <section className="surface"><EmptyState icon="playground" title="Select an agent to start" description="The Playground needs a saved definition before it can execute a run." action={<Button icon="builder" onClick={onBuild}>Build an agent</Button>} /></section> : (
        <section className="playground-shell">
          <div className="conversation-panel">
            <div className="panel-toolbar"><div className="active-agent"><span className="agent-avatar"><Icon name="spark" /></span><div><strong>{selected.name}</strong><small>{selected.runtime_mode === "mock" ? "Deterministic mock runtime" : selected.model ?? "OpenAI runtime"}</small></div></div><div className="toolbar-actions">{run && <StatusBadge status={run.status} />}{run && (run.status === "pending" || run.status === "running") && <Button variant="secondary" icon="close" onClick={onCancel}>Cancel run</Button>}<Button variant="ghost" icon="trash" onClick={onRequestClear} disabled={!run || submitting}>Clear</Button></div></div>
            <div className="conversation" aria-live="polite" aria-busy={submitting}>
              {!run ? <div className="conversation-welcome"><span><Icon name="spark" /></span><h2>Ready to test {selected.name}</h2><p>Send a message to begin a real run. The trace panel will update as the runtime emits events.</p><div className="suggestion-list"><button type="button" onClick={() => onInput("Calculate 128 * 37 + 456")}><Icon name="calculator" />Calculate 128 × 37 + 456<Icon name="arrow" /></button><button type="button" onClick={() => onInput("Calculate (42 + 18) / 3")}><Icon name="calculator" />Try a second expression<Icon name="arrow" /></button></div></div> : <div className="message-list"><article className="chat-message user"><div className="message-meta"><span>You</span><time>{new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit" }).format(new Date(run.created_at))}</time></div><p>{run.input}</p></article><article className="chat-message agent"><div className="message-meta"><span><i><Icon name="spark" /></i>{selected.name}</span><span>{run.status}</span></div>{(run.status === "pending" || run.status === "running") && <div className="thinking"><span /><span /><span /><p>Working through the {selected.runtime_mode} runtime…</p></div>}{run.status === "completed" && <div className="agent-answer"><p>{run.output}</p><small><Icon name="check" />Generated from a persisted Agent Studio run</small></div>}{run.status === "failed" && <div className="message-error" role="alert"><Icon name="error" /><div><strong>Run failed</strong><p>{run.error ?? "The runtime did not complete this request."}</p></div></div>}{run.status === "cancelled" && <div className="message-error cancelled" role="status"><Icon name="close" /><div><strong>Run cancelled</strong><p>{run.error ?? "The run was cancelled before completion. Its persisted trace remains available."}</p></div></div>}</article></div>}
            </div>
            <form className="composer" onSubmit={onRun}><label htmlFor="run-input" className="sr-only">Message</label><textarea id="run-input" value={input} onChange={(event) => onInput(event.target.value)} onKeyDown={onComposerKeyDown} placeholder="Ask your agent to calculate something…" rows={3} required disabled={submitting} /><div className="composer-footer"><div><span className="runtime-chip"><Icon name="terminal" />{selected.runtime_mode}</span><small>⌘ Enter to run</small></div><Button type="submit" icon="send" disabled={submitting || !input.trim()}>{submitting ? "Starting run…" : "Run agent"}</Button></div></form>
          </div>
          <aside className="trace-panel" aria-label="Live trace panel">
            <div className="trace-toolbar"><div><span className="live-dot" /><strong>Live trace</strong><small>{events.length ? `${events.length} events` : "Waiting for run"}</small></div>{run && <button className="inspect-link" onClick={onInspect}>Run detail <Icon name="arrow" /></button>}</div>
            <div className="trace-scroll"><TraceTimeline events={events} /></div>
          </aside>
        </section>
      )}
    </>
  );
}
