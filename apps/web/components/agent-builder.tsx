"use client";

import { FormEvent, useState } from "react";

import { Icon } from "@/components/icons";
import { Button, LoadingSkeleton, PageHeader, StatusBadge } from "@/components/ui";
import type { AgentDefinition, KnowledgeBase, RuntimeMode } from "@/lib/api";

interface BuilderDraft {
  name: string;
  prompt: string;
  runtime: RuntimeMode;
  model: string;
  calculator: boolean;
  knowledgeBaseIds: string[];
}

const initialDraft: BuilderDraft = {
  name: "Calculator Agent",
  prompt: "Use the calculator tool for arithmetic and return the exact result.",
  runtime: "mock",
  model: "",
  calculator: true,
  knowledgeBaseIds: [],
};

interface AgentBuilderProps {
  saving: boolean;
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
  }) => Promise<AgentDefinition | null>;
}

export function AgentBuilder({ saving, knowledgeBases, knowledgeLoading, knowledgeError, onReloadKnowledge, onSave }: AgentBuilderProps) {
  const [draft, setDraft] = useState(initialDraft);
  const [validation, setValidation] = useState<string | null>(null);
  const set = <K extends keyof BuilderDraft>(key: K, value: BuilderDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const knowledgeEnabled = draft.knowledgeBaseIds.length > 0;

  function toggleKnowledge(baseId: string, checked: boolean) {
    set("knowledgeBaseIds", checked ? [...draft.knowledgeBaseIds, baseId] : draft.knowledgeBaseIds.filter((id) => id !== baseId));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.name.trim() || !draft.prompt.trim()) { setValidation("Name and prompt are required."); return; }
    if (!draft.calculator && !knowledgeEnabled) { setValidation("Enable Calculator or bind at least one Knowledge Base."); return; }
    if (draft.runtime === "openai" && !draft.model.trim()) { setValidation("Enter a provider model ID for OpenAI mode."); return; }
    setValidation(null);
    const tools = [draft.calculator ? "calculator" : null, knowledgeEnabled ? "knowledge_search" : null].filter((tool): tool is string => tool !== null);
    const created = await onSave({
      name: draft.name.trim(),
      instructions: draft.prompt.trim(),
      runtime_mode: draft.runtime,
      model: draft.runtime === "openai" ? draft.model.trim() : null,
      tools,
      knowledge_base_ids: draft.knowledgeBaseIds,
    });
    if (created) setDraft(initialDraft);
  }

  return (
    <>
      <PageHeader eyebrow="Definition editor" title="Agent Builder" description="Configure runtime behavior and preview the persisted definition before saving it." />
      <div className="builder-layout">
        <form className="surface builder-form" onSubmit={submit}>
          <div className="builder-section-heading"><span>01</span><div><h2>Identity & behavior</h2><p>Core fields persisted by the Agent Studio API.</p></div></div>
          {validation && <div className="inline-error" role="alert"><Icon name="error" />{validation}</div>}
          <label className="field"><span>Name</span><small>A recognizable name for runs and traces.</small><input value={draft.name} onChange={(event) => set("name", event.target.value)} maxLength={120} required disabled={saving} /></label>
          <label className="field"><span>Prompt</span><small>Instructions used by the selected runtime.</small><textarea value={draft.prompt} onChange={(event) => set("prompt", event.target.value)} rows={7} maxLength={8000} required disabled={saving} /></label>

          <div className="builder-section-heading"><span>02</span><div><h2>Runtime</h2><p>Choose the deterministic test path or opt into a configured provider.</p></div></div>
          <fieldset className="segmented-field"><legend>Runtime mode</legend><label className={draft.runtime === "mock" ? "selected" : ""}><input type="radio" name="runtime" value="mock" checked={draft.runtime === "mock"} onChange={() => set("runtime", "mock")} /><span><Icon name="terminal" /><strong>Mock</strong><small>No API key</small></span></label><label className={draft.runtime === "openai" ? "selected" : ""}><input type="radio" name="runtime" value="openai" checked={draft.runtime === "openai"} onChange={() => set("runtime", "openai")} /><span><Icon name="spark" /><strong>OpenAI</strong><small>Credential required</small></span></label></fieldset>
          <label className="field"><span>Model</span><small>{draft.runtime === "mock" ? "The mock runtime is deterministic and does not call a model." : "Use the exact model ID configured for your provider."}</small><input value={draft.runtime === "mock" ? "Deterministic mock" : draft.model} onChange={(event) => set("model", event.target.value)} placeholder="Enter provider model ID" disabled={saving || draft.runtime === "mock"} required={draft.runtime === "openai"} /></label>

          <div className="builder-section-heading"><span>03</span><div><h2>Capabilities</h2><p>Only capabilities backed by the current backend contract can be enabled.</p></div></div>
          <div className="capability-list">
            <label className="capability-row"><span className="capability-icon calculator"><Icon name="calculator" /></span><span><strong>Calculator</strong><small>Safe arithmetic expressions</small></span><input aria-label="Enable Calculator" className="switch" type="checkbox" checked={draft.calculator} onChange={(event) => set("calculator", event.target.checked)} disabled={saving} /></label>
            <section className="knowledge-binding" aria-labelledby="knowledge-binding-title" aria-busy={knowledgeLoading}>
              <div className="capability-row"><span className="capability-icon"><Icon name="knowledge" /></span><span><strong id="knowledge-binding-title">Knowledge</strong><small>Bind real Knowledge Bases to enable knowledge_search</small></span><StatusBadge status={knowledgeEnabled ? "ready" : "idle"} /></div>
              {knowledgeLoading ? <LoadingSkeleton rows={2} /> : knowledgeError ? <div className="inline-error" role="alert"><Icon name="error" /><span>{knowledgeError}</span><Button type="button" variant="secondary" icon="refresh" onClick={onReloadKnowledge}>Retry</Button></div> : knowledgeBases.length === 0 ? <div className="builder-empty-state"><Icon name="knowledge" /><div><strong>No Knowledge Bases available</strong><p>Create and ingest one in Knowledge / RAG below, then bind it here.</p></div></div> : <div className="knowledge-binding-list">{knowledgeBases.map((base) => <label key={base.id}><input type="checkbox" checked={draft.knowledgeBaseIds.includes(base.id)} onChange={(event) => toggleKnowledge(base.id, event.target.checked)} disabled={saving} /><span><strong>{base.name}</strong><small>{base.document_count} document{base.document_count === 1 ? "" : "s"} · {base.embedding_model}</small></span></label>)}</div>}
            </section>
            <div className="capability-row unavailable" aria-disabled="true"><span className="capability-icon"><Icon name="memory" /></span><span><strong>Memory</strong><small>Available after the Durable Memory feature merges</small></span><button type="button" disabled>Unavailable</button></div>
          </div>

          <div className="builder-section-heading"><span>04</span><div><h2>Limits</h2><p>The current Agent API does not expose editable runtime limits.</p></div></div>
          <div className="field-grid"><label className="field"><span>Max iterations</span><input value="Engine default" disabled /></label><label className="field"><span>Timeout</span><input value="Engine default" disabled /></label></div>
          <div className="form-actions"><Button type="button" variant="ghost" onClick={() => { setDraft(initialDraft); setValidation(null); }} disabled={saving}>Reset</Button><Button type="submit" icon="check" disabled={saving || !draft.name.trim() || !draft.prompt.trim()}>{saving ? "Saving definition…" : "Save agent"}</Button></div>
        </form>

        <aside className="builder-preview" aria-label="Live agent preview">
          <div className="preview-toolbar"><div><span className="live-dot" />Live preview</div><span>Unsaved definition</span></div>
          <div className="preview-canvas">
            <article className="preview-card">
              <div className="preview-card-top"><span className="agent-avatar large"><Icon name="spark" /></span><StatusBadge status={draft.runtime === "mock" ? "ready" : "needs-key"} /></div>
              <p className="preview-label">Agent definition</p><h2>{draft.name || "Untitled agent"}</h2><p className="preview-prompt">{draft.prompt || "Your agent prompt will appear here."}</p>
              <div className="preview-divider" />
              <dl className="preview-details"><div><dt><Icon name="model" />Runtime</dt><dd>{draft.runtime === "mock" ? "Deterministic mock" : draft.model || "Model not set"}</dd></div><div><dt><Icon name="tool" />Tools</dt><dd><span className="tool-chip-row">{draft.calculator && <span className="tool-chip"><Icon name="calculator" />calculator</span>}{knowledgeEnabled && <span className="tool-chip"><Icon name="knowledge" />knowledge_search</span>}{!draft.calculator && !knowledgeEnabled && "No tools"}</span></dd></div><div><dt><Icon name="knowledge" />Knowledge</dt><dd>{knowledgeEnabled ? `${draft.knowledgeBaseIds.length} base${draft.knowledgeBaseIds.length === 1 ? "" : "s"} bound` : "Not bound"}</dd></div><div><dt><Icon name="memory" />Memory</dt><dd>Unavailable</dd></div></dl>
              <Button className="preview-run" icon="play" disabled>Run after saving</Button>
            </article>
            <div className="preview-note"><Icon name="info" /><p><strong>Preview only</strong><br />Saving creates a real backend definition. Unsupported capabilities stay disabled.</p></div>
          </div>
        </aside>
      </div>
    </>
  );
}
