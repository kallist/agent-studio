"use client";

import { FormEvent, KeyboardEvent } from "react";

import { Icon } from "@/components/icons";
import { TraceTimeline } from "@/components/trace-timeline";
import { Button, EmptyState, PageHeader, StatusBadge } from "@/components/ui";
import { displayStatus } from "@/i18n/display";
import { useI18n } from "@/i18n/provider";
import type { AgentDefinition, AgentEvent, RunResult } from "@/lib/api";

export function Playground({ agents, selected, run, events, input, submitting, onSelectAgent, onInput, onRun, onCancel, onBuild, onInspect, onRequestClear }: { agents: AgentDefinition[]; selected: AgentDefinition | null; run: RunResult | null; events: AgentEvent[]; input: string; submitting: boolean; onSelectAgent: (id: string) => void; onInput: (value: string) => void; onRun: (event: FormEvent<HTMLFormElement>) => void; onCancel: () => void; onBuild: () => void; onInspect: () => void; onRequestClear: () => void }) {
  const { locale, t } = useI18n();
  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && input.trim() && !submitting) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };
  return (
    <>
      <PageHeader eyebrow={t("playground.eyebrow")} title={t("playground.title")} description={t("playground.description")} action={selected && <div className="agent-select-wrap"><label htmlFor="active-agent">{t("playground.activeAgent")}</label><select id="active-agent" value={selected.id} onChange={(event) => onSelectAgent(event.target.value)}>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></div>} />
      {!selected ? <section className="surface"><EmptyState icon="playground" title={t("playground.emptyTitle")} description={t("playground.emptyDescription")} action={<Button icon="builder" onClick={onBuild}>{t("playground.build")}</Button>} /></section> : (
        <section className="playground-shell">
          <div className="conversation-panel">
            <div className="panel-toolbar"><div className="active-agent"><span className="agent-avatar"><Icon name="spark" /></span><div><strong>{selected.name}</strong><small>{selected.runtime_mode === "mock" ? t("playground.deterministicRuntime") : selected.model ?? t("playground.openAiRuntime")}</small></div></div><div className="toolbar-actions">{run && <StatusBadge status={run.status} />}{run && (run.status === "pending" || run.status === "running") && <Button variant="secondary" icon="close" onClick={onCancel}>{t("playground.cancelRun")}</Button>}<Button variant="ghost" icon="trash" onClick={onRequestClear} disabled={!run || submitting}>{t("common.actions.clear")}</Button></div></div>
            <div className="conversation" aria-live="polite" aria-busy={submitting}>
              {!run ? <div className="conversation-welcome"><span><Icon name="spark" /></span><h2>{t("playground.ready", { name: selected.name })}</h2><p>{t("playground.readyHelp")}</p><div className="suggestion-list"><button type="button" onClick={() => onInput("Calculate 128 * 37 + 456")}><Icon name="calculator" />{t("playground.suggestionOne")}<Icon name="arrow" /></button><button type="button" onClick={() => onInput("Calculate (42 + 18) / 3")}><Icon name="calculator" />{t("playground.suggestionTwo")}<Icon name="arrow" /></button></div></div> : <div className="message-list"><article className="chat-message user"><div className="message-meta"><span>{t("playground.you")}</span><time>{new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(new Date(run.created_at))}</time></div><p>{run.input}</p></article><article className="chat-message agent"><div className="message-meta"><span><i><Icon name="spark" /></i>{selected.name}</span><span>{displayStatus(t, run.status)}</span></div>{(run.status === "pending" || run.status === "running") && <div className="thinking"><span /><span /><span /><p>{t("playground.working", { runtime: selected.runtime_mode })}</p></div>}{run.status === "completed" && <div className="agent-answer"><p>{run.output}</p><small><Icon name="check" />{t("playground.persistedOutput")}</small></div>}{run.status === "failed" && <div className="message-error" role="alert"><Icon name="error" /><div><strong>{t("playground.failedTitle")}</strong><p>{run.error ?? t("playground.failedHelp")}</p></div></div>}{run.status === "cancelled" && <div className="message-error cancelled" role="status"><Icon name="close" /><div><strong>{t("playground.cancelledTitle")}</strong><p>{run.error ?? t("playground.cancelledHelp")}</p></div></div>}</article></div>}
            </div>
            <form className="composer" onSubmit={onRun}><label htmlFor="run-input" className="sr-only">{t("playground.message")}</label><textarea id="run-input" value={input} onChange={(event) => onInput(event.target.value)} onKeyDown={onComposerKeyDown} placeholder={t("playground.placeholder")} rows={3} required disabled={submitting} /><div className="composer-footer"><div><span className="runtime-chip"><Icon name="terminal" />{selected.runtime_mode}</span><small>{t("playground.shortcut")}</small></div><Button type="submit" icon="send" disabled={submitting || !input.trim()}>{submitting ? t("playground.starting") : t("playground.runAgent")}</Button></div></form>
          </div>
          <aside className="trace-panel" aria-label={t("playground.tracePanel")}>
            <div className="trace-toolbar"><div><span className="live-dot" /><strong>{t("playground.liveTrace")}</strong><small>{events.length ? t("common.counts.events", { count: events.length }) : t("playground.waiting")}</small></div>{run && <button className="inspect-link" onClick={onInspect}>{t("playground.runDetail")} <Icon name="arrow" /></button>}</div>
            <div className="trace-scroll"><TraceTimeline events={events} /></div>
          </aside>
        </section>
      )}
    </>
  );
}
