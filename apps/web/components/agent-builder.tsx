"use client";

import { FormEvent, useState } from "react";

import { Icon } from "@/components/icons";
import { Button, LoadingSkeleton, PageHeader, StatusBadge } from "@/components/ui";
import { useI18n } from "@/i18n/provider";
import type { AgentDefinition, KnowledgeBase, ProviderCatalogReadiness, RuntimeMode } from "@/lib/api";

interface BuilderDraft {
  name: string;
  prompt: string;
  runtime: RuntimeMode;
  model: string;
  calculator: boolean;
  knowledgeBaseIds: string[];
  memoryEnabled: boolean;
}

const initialDraft: BuilderDraft = {
  name: "Calculator Agent",
  prompt: "Use the calculator tool for arithmetic and return the exact result.",
  runtime: "mock",
  model: "",
  calculator: true,
  knowledgeBaseIds: [],
  memoryEnabled: true,
};

interface AgentBuilderProps {
  saving: boolean;
  providerReadiness: ProviderCatalogReadiness | null;
  knowledgeBases: KnowledgeBase[];
  knowledgeLoading: boolean;
  knowledgeError: string | null;
  onReloadKnowledge: () => void;
  onSave: (payload: {
    name: string;
    instructions: string;
    runtime_mode: RuntimeMode;
    model: string | null;
    tools: string[];
    knowledge_base_ids: string[];
    memory_enabled: boolean;
  }) => Promise<AgentDefinition | null>;
}

export function AgentBuilder({ saving, providerReadiness, knowledgeBases, knowledgeLoading, knowledgeError, onReloadKnowledge, onSave }: AgentBuilderProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(initialDraft);
  const [validation, setValidation] = useState<string | null>(null);
  const set = <K extends keyof BuilderDraft>(key: K, value: BuilderDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const knowledgeEnabled = draft.knowledgeBaseIds.length > 0;
  const selectedProvider = draft.runtime === "mock" ? null : providerReadiness?.providers.find((item) => item.provider === draft.runtime) ?? null;

  function toggleKnowledge(baseId: string, checked: boolean) {
    set("knowledgeBaseIds", checked ? [...draft.knowledgeBaseIds, baseId] : draft.knowledgeBaseIds.filter((id) => id !== baseId));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.name.trim() || !draft.prompt.trim()) { setValidation(t("builder.required")); return; }
    if (draft.runtime !== "mock" && !draft.model.trim()) { setValidation(t("builder.modelRequired", { provider: draft.runtime === "openai" ? "OpenAI" : "DeepSeek" })); return; }
    setValidation(null);
    const tools = [draft.calculator ? "calculator" : null, knowledgeEnabled ? "knowledge_search" : null].filter((tool): tool is string => tool !== null);
    const created = await onSave({
      name: draft.name.trim(),
      instructions: draft.prompt.trim(),
      runtime_mode: draft.runtime,
      model: draft.runtime !== "mock" ? draft.model.trim() : null,
      tools,
      knowledge_base_ids: draft.knowledgeBaseIds,
      memory_enabled: draft.memoryEnabled,
    });
    if (created) setDraft(initialDraft);
  }

  return (
    <>
      <PageHeader eyebrow={t("builder.eyebrow")} title={t("builder.title")} description={t("builder.description")} />
      <div className="builder-layout">
        <form className="surface builder-form" onSubmit={submit}>
          <div className="builder-section-heading"><span>01</span><div><h2>{t("builder.identity")}</h2><p>{t("builder.identityHelp")}</p></div></div>
          {validation && <div className="inline-error" role="alert"><Icon name="error" />{validation}</div>}
          <label className="field"><span>{t("builder.name")}</span><small>{t("builder.nameHelp")}</small><input value={draft.name} onChange={(event) => set("name", event.target.value)} maxLength={120} required disabled={saving} /></label>
          <label className="field"><span>{t("builder.prompt")}</span><small>{t("builder.promptHelp")}</small><textarea value={draft.prompt} onChange={(event) => set("prompt", event.target.value)} rows={7} maxLength={8000} required disabled={saving} /></label>

          <div className="builder-section-heading"><span>02</span><div><h2>{t("builder.runtime")}</h2><p>{t("builder.runtimeHelp")}</p></div></div>
          <fieldset className="segmented-field"><legend>{t("builder.runtimeMode")}</legend><label className={draft.runtime === "mock" ? "selected" : ""}><input type="radio" name="runtime" value="mock" checked={draft.runtime === "mock"} onChange={() => set("runtime", "mock")} /><span><Icon name="terminal" /><strong>Mock</strong><small>{t("builder.noApiKey")}</small></span></label><label className={draft.runtime === "openai" ? "selected" : ""}><input type="radio" name="runtime" value="openai" checked={draft.runtime === "openai"} onChange={() => { set("runtime", "openai"); set("model", providerReadiness?.providers.find((item) => item.provider === "openai")?.default_model ?? ""); }} /><span><Icon name="spark" /><strong>OpenAI</strong><small>Responses API</small></span></label><label className={draft.runtime === "deepseek" ? "selected" : ""}><input type="radio" name="runtime" value="deepseek" checked={draft.runtime === "deepseek"} onChange={() => { set("runtime", "deepseek"); set("model", providerReadiness?.providers.find((item) => item.provider === "deepseek")?.default_model ?? ""); }} /><span><Icon name="spark" /><strong>DeepSeek</strong><small>Chat Completions</small></span></label></fieldset>
          <label className="field"><span>{t("builder.model")}</span><small>{draft.runtime === "mock" ? t("builder.mockHelp") : selectedProvider?.configured ? t("builder.configuredHelp", { provider: draft.runtime === "openai" ? "OpenAI" : "DeepSeek" }) : t("builder.unconfiguredHelp", { provider: draft.runtime === "openai" ? "OpenAI" : "DeepSeek" })}</small><input value={draft.runtime === "mock" ? t("builder.deterministicMock") : draft.model} onChange={(event) => set("model", event.target.value)} placeholder={t("builder.modelPlaceholder")} disabled={saving || draft.runtime === "mock"} required={draft.runtime !== "mock"} /></label>

          <div className="builder-section-heading"><span>03</span><div><h2>{t("builder.capabilities")}</h2><p>{t("builder.capabilitiesHelp")}</p></div></div>
          <div className="capability-list">
            <label className="capability-row"><span className="capability-icon calculator"><Icon name="calculator" /></span><span><strong>{t("builder.calculator")}</strong><small>{t("builder.calculatorHelp")}</small></span><input aria-label={t("builder.enableCalculator")} className="switch" type="checkbox" checked={draft.calculator} onChange={(event) => set("calculator", event.target.checked)} disabled={saving} /></label>
            <section className="knowledge-binding" aria-labelledby="knowledge-binding-title" aria-busy={knowledgeLoading}>
              <div className="capability-row"><span className="capability-icon"><Icon name="knowledge" /></span><span><strong id="knowledge-binding-title">{t("builder.knowledge")}</strong><small>{t("builder.knowledgeHelp")}</small></span><StatusBadge status={knowledgeEnabled ? "ready" : "idle"} /></div>
              {knowledgeLoading ? <LoadingSkeleton rows={2} /> : knowledgeError ? <div className="inline-error" role="alert"><Icon name="error" /><span>{knowledgeError}</span><Button type="button" variant="secondary" icon="refresh" onClick={onReloadKnowledge}>{t("common.actions.retry")}</Button></div> : knowledgeBases.length === 0 ? <div className="builder-empty-state"><Icon name="knowledge" /><div><strong>{t("builder.noKnowledge")}</strong><p>{t("builder.noKnowledgeHelp")}</p></div></div> : <div className="knowledge-binding-list">{knowledgeBases.map((base) => <label key={base.id}><input type="checkbox" checked={draft.knowledgeBaseIds.includes(base.id)} onChange={(event) => toggleKnowledge(base.id, event.target.checked)} disabled={saving} /><span><strong>{base.name}</strong><small>{t(base.document_count === 1 ? "common.counts.documentsOne" : "common.counts.documentsOther", { count: base.document_count })} · {base.embedding_model} · {base.embedding_dimensions}d</small></span></label>)}</div>}
            </section>
            <label className="capability-row"><span className="capability-icon"><Icon name="memory" /></span><span><strong>{t("builder.durableMemory")}</strong><small>{t("builder.durableMemoryHelp")}</small></span><input aria-label={t("builder.enableMemory")} className="switch" type="checkbox" checked={draft.memoryEnabled} onChange={(event) => set("memoryEnabled", event.target.checked)} disabled={saving} /></label>
          </div>

          <div className="builder-section-heading"><span>04</span><div><h2>{t("builder.limits")}</h2><p>{t("builder.limitsHelp")}</p></div></div>
          <div className="field-grid"><label className="field"><span>{t("builder.maxIterations")}</span><input value={t("builder.engineDefault")} disabled /></label><label className="field"><span>{t("builder.timeout")}</span><input value={t("builder.engineDefault")} disabled /></label></div>
          <div className="form-actions"><Button type="button" variant="ghost" onClick={() => { setDraft(initialDraft); setValidation(null); }} disabled={saving}>{t("common.actions.reset")}</Button><Button type="submit" icon="check" disabled={saving || !draft.name.trim() || !draft.prompt.trim()}>{saving ? t("builder.saving") : t("builder.saveAgent")}</Button></div>
        </form>

        <aside className="builder-preview" aria-label={t("builder.previewAria")}>
          <div className="preview-toolbar"><div><span className="live-dot" />{t("builder.livePreview")}</div><span>{t("builder.unsaved")}</span></div>
          <div className="preview-canvas">
            <article className="preview-card">
              <div className="preview-card-top"><span className="agent-avatar large"><Icon name="spark" /></span><StatusBadge status={draft.runtime === "mock" || selectedProvider?.configured ? "ready" : "needs-key"} /></div>
              <p className="preview-label">{t("builder.definition")}</p><h2>{draft.name || t("builder.untitled")}</h2><p className="preview-prompt">{draft.prompt || t("builder.promptPlaceholder")}</p>
              <div className="preview-divider" />
              <dl className="preview-details"><div><dt><Icon name="model" />Runtime</dt><dd>{draft.runtime === "mock" ? t("builder.deterministicMock") : draft.model || t("builder.modelNotSet")}</dd></div><div><dt><Icon name="tool" />{t("builder.tools")}</dt><dd><span className="tool-chip-row">{draft.calculator && <span className="tool-chip"><Icon name="calculator" />calculator</span>}{knowledgeEnabled && <span className="tool-chip"><Icon name="knowledge" />knowledge_search</span>}{!draft.calculator && !knowledgeEnabled && t("builder.noTools")}</span></dd></div><div><dt><Icon name="knowledge" />{t("builder.knowledge")}</dt><dd>{knowledgeEnabled ? t(draft.knowledgeBaseIds.length === 1 ? "common.counts.basesOne" : "common.counts.basesOther", { count: draft.knowledgeBaseIds.length }) : t("builder.notBound")}</dd></div><div><dt><Icon name="memory" />{t("agents.memory")}</dt><dd>{draft.memoryEnabled ? t("common.states.enabled") : t("common.states.disabled")}</dd></div></dl>
              <Button className="preview-run" icon="play" disabled>{t("builder.runAfterSaving")}</Button>
            </article>
            <div className="preview-note"><Icon name="info" /><p><strong>{t("builder.previewOnly")}</strong><br />{t("builder.previewNote")}</p></div>
          </div>
        </aside>
      </div>
    </>
  );
}
