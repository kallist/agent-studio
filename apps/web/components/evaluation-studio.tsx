"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { Icon } from "@/components/icons";
import { Button, EmptyState, LoadingSkeleton, PageHeader, useRelativeTime } from "@/components/ui";
import { displayStatus } from "@/i18n/display";
import { useI18n, type Translate, type TranslationKey } from "@/i18n/provider";
import {
  AgentDefinition,
  EvaluationCase,
  EvaluationCaseInput,
  EvaluationCaseResult,
  EvaluationCaseStatus,
  EvaluationRun,
  EvaluationSuite,
  EvaluationSuiteSummary,
  GraderConfig,
  GraderType,
  RunStatus,
  api,
} from "@/lib/api";

type Screen = "list" | "builder" | "suite" | "run";
type ResultFilter = "all" | EvaluationCaseStatus;

interface DraftCase extends EvaluationCaseInput {
  clientId: string;
  id?: string;
  memorySeed: string;
}

const graderTypes: Array<{ value: GraderType; label: TranslationKey }> = [
  { value: "run_status", label: "evaluation.graderTypes.runStatus" },
  { value: "final_output_non_empty", label: "evaluation.graderTypes.finalOutput" },
  { value: "exact_match", label: "evaluation.graderTypes.exactMatch" },
  { value: "contains", label: "evaluation.graderTypes.contains" },
  { value: "tool_selected", label: "evaluation.graderTypes.toolSelected" },
  { value: "tool_not_selected", label: "evaluation.graderTypes.toolNotSelected" },
  { value: "retrieval_hit", label: "evaluation.graderTypes.retrievalHit" },
  { value: "citation", label: "evaluation.graderTypes.citation" },
  { value: "memory_retrieved", label: "evaluation.graderTypes.memoryRetrieved" },
  { value: "max_steps", label: "evaluation.graderTypes.maxSteps" },
  { value: "max_duration", label: "evaluation.graderTypes.maxDuration" },
];

const terminalEvaluationStatuses = new Set(["completed", "failed", "cancelled"]);

function newGrader(type: GraderType = "run_status"): GraderConfig {
  return {
    type,
    required: true,
    value: type === "contains" || type === "exact_match" ? "" : null,
    case_sensitive: true,
    tool_name: type === "tool_selected" || type === "tool_not_selected" ? "calculator" : null,
    expected_source: null,
    expected_document_id: null,
    expected_status: type === "run_status" ? "completed" : null,
    maximum: type === "max_steps" ? 3 : type === "max_duration" ? 30000 : null,
  };
}

function newCase(): DraftCase {
  return {
    clientId: crypto.randomUUID(),
    name: "Calculator basic arithmetic",
    input: "Calculate 128 * 37 + 456",
    enabled: true,
    graders: [newGrader("run_status"), newGrader("contains"), newGrader("tool_selected")],
    setup: { memories: [] },
    memorySeed: "",
  };
}

function toDraftCase(item: EvaluationCase): DraftCase {
  return {
    clientId: item.id,
    id: item.id,
    name: item.name,
    input: item.input,
    enabled: item.enabled,
    graders: item.graders,
    setup: item.setup,
    memorySeed: item.setup.memories[0]?.content ?? "",
  };
}

function toPayload(item: DraftCase): EvaluationCaseInput {
  return {
    name: item.name.trim(),
    input: item.input.trim(),
    enabled: item.enabled,
    graders: item.graders,
    setup: {
      memories: item.memorySeed.trim()
        ? [{ content: item.memorySeed.trim(), importance: 0.9 }]
        : [],
    },
  };
}

export function formatEvaluationRate(value: number | null): string {
  return value === null ? "N/A" : `${Math.round(value * 100)}%`;
}

export function filterEvaluationResults(
  results: EvaluationCaseResult[],
  filter: ResultFilter,
): EvaluationCaseResult[] {
  return filter === "all" ? results : results.filter((result) => result.status === filter);
}

function statusLabel(t: Translate, status: string | null): string {
  return displayStatus(t, status).toUpperCase();
}

function snapshotName(snapshot: Record<string, unknown>, t: Translate): string {
  return typeof snapshot.name === "string" ? snapshot.name : t("evaluation.caseFallback");
}

function graderLabel(type: GraderType, t: Translate): string {
  const key = graderTypes.find((item) => item.value === type)?.label;
  return key ? t(key) : type;
}

export function EvaluationStudio({
  agents,
  onViewRun,
}: {
  agents: AgentDefinition[];
  onViewRun: (runId: string) => void;
}) {
  const { t } = useI18n();
  const [screen, setScreen] = useState<Screen>("list");
  const [suites, setSuites] = useState<EvaluationSuiteSummary[]>([]);
  const [suite, setSuite] = useState<EvaluationSuite | null>(null);
  const [evaluationRun, setEvaluationRun] = useState<EvaluationRun | null>(null);
  const [results, setResults] = useState<EvaluationCaseResult[]>([]);
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null);
  const [filter, setFilter] = useState<ResultFilter>("all");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollRevision, setPollRevision] = useState(0);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [agentId, setAgentId] = useState("");
  const [draftCases, setDraftCases] = useState<DraftCase[]>([newCase()]);

  const loadSuites = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSuites(await api.listEvaluationSuites());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("evaluation.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    const timeout = window.setTimeout(() => { void loadSuites(); }, 0);
    return () => window.clearTimeout(timeout);
  }, [loadSuites]);

  const activeEvaluationRunId = screen === "run"
    && evaluationRun
    && !terminalEvaluationStatuses.has(evaluationRun.status)
    ? evaluationRun.id
    : null;

  useEffect(() => {
    if (!activeEvaluationRunId) return;
    let disposed = false;
    let failures = 0;
    let timeout: number | undefined;
    const poll = async () => {
      try {
        const [run, caseResults] = await Promise.all([
          api.getEvaluationRun(activeEvaluationRunId),
          api.listEvaluationResults(activeEvaluationRunId),
        ]);
        if (disposed) return;
        failures = 0;
        setError(null);
        setEvaluationRun(run);
        setResults(caseResults);
        setSelectedResultId((current) => current && caseResults.some((item) => item.id === current)
          ? current
          : caseResults.find((item) => item.status === "fail" || item.status === "error")?.id ?? caseResults[0]?.id ?? null);
        if (terminalEvaluationStatuses.has(run.status)) {
          setSaving(false);
          void loadSuites();
          return;
        }
        timeout = window.setTimeout(() => { void poll(); }, 500);
      } catch (reason) {
        if (disposed) return;
        failures += 1;
        setError(reason instanceof Error ? reason.message : t("evaluation.refreshFailed"));
        if (failures < 5) {
          const delay = Math.min(250 * (2 ** (failures - 1)), 4_000);
          timeout = window.setTimeout(() => { void poll(); }, delay);
          return;
        }
        setSaving(false);
      }
    };
    timeout = window.setTimeout(() => { void poll(); }, 100);
    return () => {
      disposed = true;
      if (timeout !== undefined) window.clearTimeout(timeout);
    };
  }, [activeEvaluationRunId, loadSuites, pollRevision, t]);

  const openSuite = useCallback(async (suiteId: string) => {
    setLoading(true);
    setError(null);
    try {
      const loaded = await api.getEvaluationSuite(suiteId);
      setSuite(loaded);
      setScreen("suite");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("evaluation.suiteLoadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  function openBuilder(current?: EvaluationSuite) {
    setSuite(current ?? null);
    setName(current?.name ?? "");
    setDescription(current?.description ?? "");
    setAgentId(current?.agent_id ?? agents[0]?.id ?? "");
    setDraftCases(current?.cases.map(toDraftCase) ?? [newCase()]);
    setError(null);
    setScreen("builder");
  }

  function updateCase(clientId: string, update: Partial<DraftCase>) {
    setDraftCases((current) => current.map((item) => item.clientId === clientId ? { ...item, ...update } : item));
  }

  function updateGrader(clientId: string, index: number, update: Partial<GraderConfig>) {
    setDraftCases((current) => current.map((item) => {
      if (item.clientId !== clientId) return item;
      return {
        ...item,
        graders: item.graders.map((grader, graderIndex) => graderIndex === index ? { ...grader, ...update } : grader),
      };
    }));
  }

  async function saveSuite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!agentId || !name.trim() || draftCases.length === 0) return;
    setSaving(true);
    setError(null);
    try {
      let saved: EvaluationSuite;
      if (suite) {
        await api.updateEvaluationSuite(suite.id, {
          name: name.trim(),
          description: description.trim(),
          agent_id: agentId,
        });
        const currentIds = new Set(draftCases.flatMap((item) => item.id ? [item.id] : []));
        await Promise.all(suite.cases.filter((item) => !currentIds.has(item.id)).map((item) => api.deleteEvaluationCase(item.id)));
        await Promise.all(draftCases.map((item) => item.id
          ? api.updateEvaluationCase(item.id, toPayload(item))
          : api.createEvaluationCase(suite.id, toPayload(item))));
        saved = await api.getEvaluationSuite(suite.id);
      } else {
        saved = await api.createEvaluationSuite({
          name: name.trim(),
          description: description.trim(),
          agent_id: agentId,
          cases: draftCases.map(toPayload),
        });
      }
      setSuite(saved);
      await loadSuites();
      setScreen("suite");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("evaluation.saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function deleteSuite() {
    if (!suite || !window.confirm(t("evaluation.deleteConfirm", { name: suite.name }))) return;
    setSaving(true);
    try {
      await api.deleteEvaluationSuite(suite.id);
      setSuite(null);
      setScreen("list");
      await loadSuites();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("evaluation.deleteFailed"));
    } finally {
      setSaving(false);
    }
  }

  const openEvaluationRun = useCallback(async (runId: string) => {
    setLoading(true);
    setError(null);
    try {
      const [run, caseResults] = await Promise.all([
        api.getEvaluationRun(runId),
        api.listEvaluationResults(runId),
      ]);
      setEvaluationRun(run);
      setResults(caseResults);
      setSelectedResultId(caseResults.find((item) => item.status === "fail" || item.status === "error")?.id ?? caseResults[0]?.id ?? null);
      setSaving(!terminalEvaluationStatuses.has(run.status));
      setScreen("run");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("evaluation.runLoadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  async function runEvaluation() {
    if (!suite || saving) return;
    setSaving(true);
    setError(null);
    try {
      const run = await api.startEvaluationRun(suite.id, crypto.randomUUID());
      setEvaluationRun(run);
      setResults([]);
      setScreen("run");
      if (terminalEvaluationStatuses.has(run.status)) setSaving(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("evaluation.runStartFailed"));
      setSaving(false);
    }
  }

  async function cancelEvaluation() {
    if (!evaluationRun) return;
    try {
      setEvaluationRun(await api.cancelEvaluationRun(evaluationRun.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("evaluation.cancelFailed"));
    }
  }

  function retryEvaluationRefresh() {
    setError(null);
    setSaving(true);
    setPollRevision((current) => current + 1);
  }

  const filteredResults = useMemo(() => filterEvaluationResults(results, filter), [filter, results]);
  const selectedResult = results.find((item) => item.id === selectedResultId) ?? null;

  if (screen === "builder") {
    return (
      <form className="evaluation-builder" onSubmit={saveSuite}>
        <PageHeader eyebrow={t("evaluation.builderEyebrow")} title={suite ? t("evaluation.editTitle") : t("evaluation.createTitle")} description={t("evaluation.builderDescription")} action={<Button type="button" variant="ghost" onClick={() => setScreen(suite ? "suite" : "list")}>{t("common.actions.cancel")}</Button>} />
        {error && <div className="inline-error" role="alert">{error}</div>}
        <section className="surface evaluation-form-section">
          <div className="field-grid">
            <label><span>{t("evaluation.suiteName")}</span><input required value={name} onChange={(event) => setName(event.target.value)} placeholder={t("evaluation.suitePlaceholder")} /></label>
            <label><span>{t("evaluation.agent")}</span><select required value={agentId} onChange={(event) => setAgentId(event.target.value)}><option value="">{t("evaluation.selectAgent")}</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label>
          </div>
          <label><span>{t("evaluation.descriptionLabel")}</span><textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder={t("evaluation.descriptionPlaceholder")} /></label>
        </section>
        <section className="evaluation-cases" aria-label={t("evaluation.cases")}>
          <div className="section-heading"><div><h2>{t("evaluation.cases")}</h2><p>{t("evaluation.casesDescription")}</p></div><Button type="button" variant="secondary" icon="plus" onClick={() => setDraftCases((current) => [...current, newCase()])}>{t("evaluation.addCase")}</Button></div>
          {draftCases.map((item, caseIndex) => (
            <article className="surface evaluation-case-editor" key={item.clientId}>
              <header><div><small>{t("evaluation.case", { count: caseIndex + 1 })}</small><h3>{item.name || t("evaluation.untitledCase")}</h3></div><button type="button" className="icon-button danger" aria-label={t("evaluation.deleteCase", { count: caseIndex + 1 })} disabled={draftCases.length === 1} onClick={() => setDraftCases((current) => current.filter((candidate) => candidate.clientId !== item.clientId))}><Icon name="trash" /></button></header>
              <div className="field-grid">
                <label><span>{t("evaluation.caseName")}</span><input required value={item.name} onChange={(event) => updateCase(item.clientId, { name: event.target.value })} /></label>
                <label className="checkbox-field"><input type="checkbox" checked={item.enabled} onChange={(event) => updateCase(item.clientId, { enabled: event.target.checked })} /><span>{t("evaluation.enabled")}</span></label>
              </div>
              <label><span>{t("evaluation.input")}</span><textarea required value={item.input} onChange={(event) => updateCase(item.clientId, { input: event.target.value })} /></label>
              <label><span>{t("evaluation.memorySeed")} <small>{t("evaluation.optionalIsolated")}</small></span><textarea value={item.memorySeed} onChange={(event) => updateCase(item.clientId, { memorySeed: event.target.value })} placeholder={t("evaluation.memoryPlaceholder")} /></label>
              <div className="grader-list">
                <div className="grader-heading"><strong>{t("evaluation.graders")}</strong><button type="button" onClick={() => updateCase(item.clientId, { graders: [...item.graders, newGrader()] })}><Icon name="plus" /> {t("evaluation.addGrader")}</button></div>
                {item.graders.map((grader, graderIndex) => (
                  <div className="grader-config" key={`${item.clientId}-${graderIndex}`}>
                    <select aria-label={t("evaluation.graderType", { count: graderIndex + 1 })} value={grader.type} onChange={(event) => updateGrader(item.clientId, graderIndex, newGrader(event.target.value as GraderType))}>{graderTypes.map((type) => <option key={type.value} value={type.value}>{t(type.label)}</option>)}</select>
                    <GraderFields grader={grader} onChange={(update) => updateGrader(item.clientId, graderIndex, update)} />
                    <label className="required-check"><input type="checkbox" checked={grader.required} onChange={(event) => updateGrader(item.clientId, graderIndex, { required: event.target.checked })} /> {t("evaluation.required")}</label>
                    <button type="button" className="icon-button" aria-label={t("evaluation.deleteGrader", { count: graderIndex + 1 })} disabled={item.graders.length === 1} onClick={() => updateCase(item.clientId, { graders: item.graders.filter((_candidate, index) => index !== graderIndex) })}><Icon name="trash" /></button>
                  </div>
                ))}
              </div>
            </article>
          ))}
        </section>
        <div className="form-actions"><Button type="button" variant="ghost" onClick={() => setScreen(suite ? "suite" : "list")}>{t("common.actions.cancel")}</Button><Button type="submit" icon="check" disabled={saving || !agents.length}>{saving ? t("evaluation.saving") : t("evaluation.saveSuite")}</Button></div>
      </form>
    );
  }

  if (screen === "suite" && suite) {
    return (
      <>
        <PageHeader eyebrow={t("evaluation.suiteEyebrow")} title={suite.name} description={suite.description || t("evaluation.suiteDescription")} action={<div className="button-row"><Button variant="ghost" onClick={() => setScreen("list")}>{t("evaluation.allSuites")}</Button><Button variant="secondary" icon="builder" onClick={() => openBuilder(suite)}>{t("common.actions.edit")}</Button><Button icon="play" disabled={saving || suite.cases.filter((item) => item.enabled).length === 0} onClick={() => void runEvaluation()}>{saving ? t("evaluation.starting") : t("evaluation.runEvaluation")}</Button></div>} />
        {error && <div className="inline-error" role="alert">{error}</div>}
        <section className="evaluation-suite-meta surface"><div><span>{t("evaluation.revision")}</span><strong>{suite.revision}</strong></div><div><span>{t("evaluation.cases")}</span><strong>{suite.cases.length}</strong></div><div><span>{t("evaluation.agent")}</span><strong>{agents.find((agent) => agent.id === suite.agent_id)?.name ?? suite.agent_id.slice(0, 8)}</strong></div><button className="text-danger" disabled={saving} onClick={() => void deleteSuite()}>{t("evaluation.deleteSuite")}</button></section>
        <section className="surface evaluation-case-list"><div className="section-heading"><div><h2>{t("evaluation.cases")}</h2><p>{t("evaluation.casesSnapshot")}</p></div></div>{suite.cases.map((item) => <article key={item.id}><span className={`eval-dot ${item.enabled ? "pass" : "idle"}`} /><div><strong>{item.name}</strong><p>{item.input}</p><small>{t(item.setup.memories.length ? "evaluation.caseMetaWithMemory" : "evaluation.caseMetaNoSetup", { count: item.graders.length })}</small></div><span>{item.enabled ? t("common.states.enabled") : t("common.states.disabled")}</span></article>)}</section>
      </>
    );
  }

  if (screen === "run" && evaluationRun) {
    return (
      <>
        {error && <div className="inline-error" role="alert"><span>{error}</span><Button variant="ghost" onClick={retryEvaluationRefresh}>{t("evaluation.retryRefresh")}</Button></div>}
        <EvaluationRunPanel
          run={evaluationRun}
          results={results}
          filteredResults={filteredResults}
          filter={filter}
          selectedResult={selectedResult}
          loading={loading || saving}
          onFilter={setFilter}
          onSelect={setSelectedResultId}
          onBack={() => { setSaving(false); setScreen(suite ? "suite" : "list"); }}
          onCancel={() => void cancelEvaluation()}
          onViewRun={onViewRun}
        />
      </>
    );
  }

  return (
    <>
      <PageHeader eyebrow={t("evaluation.eyebrow")} title={t("evaluation.title")} description={t("evaluation.description")} action={<Button icon="plus" disabled={!agents.length} onClick={() => openBuilder()}>{t("evaluation.createSuite")}</Button>} />
      {error && <div className="inline-error" role="alert">{error}</div>}
      {loading ? <LoadingSkeleton rows={4} /> : suites.length === 0 ? <EmptyState icon="evaluation" title={t("evaluation.emptyTitle")} description={t("evaluation.emptyDescription")} action={<Button icon="plus" disabled={!agents.length} onClick={() => openBuilder()}>{t("evaluation.createSuite")}</Button>} /> : <SuiteList suites={suites} agents={agents} onOpen={(id) => void openSuite(id)} onOpenRun={(id) => void openEvaluationRun(id)} />}
    </>
  );
}

function GraderFields({ grader, onChange }: { grader: GraderConfig; onChange: (update: Partial<GraderConfig>) => void }) {
  const { t } = useI18n();
  if (grader.type === "exact_match" || grader.type === "contains") {
    return <><input aria-label={t("evaluation.expectedText")} required value={grader.value ?? ""} onChange={(event) => onChange({ value: event.target.value })} placeholder={t("evaluation.expectedText")} /><label className="required-check"><input type="checkbox" checked={grader.case_sensitive} onChange={(event) => onChange({ case_sensitive: event.target.checked })} /> {t("evaluation.caseSensitive")}</label></>;
  }
  if (grader.type === "tool_selected" || grader.type === "tool_not_selected") {
    return <input aria-label={t("evaluation.toolName")} required value={grader.tool_name ?? ""} onChange={(event) => onChange({ tool_name: event.target.value })} placeholder="calculator" />;
  }
  if (grader.type === "retrieval_hit" || grader.type === "citation") {
    return <input aria-label={t("evaluation.expectedSource")} value={grader.expected_source ?? ""} onChange={(event) => onChange({ expected_source: event.target.value || null })} placeholder={t("evaluation.sourcePlaceholder")} />;
  }
  if (grader.type === "max_steps" || grader.type === "max_duration") {
    return <input aria-label={grader.type === "max_steps" ? t("evaluation.maximumSteps") : t("evaluation.maximumDuration")} type="number" min="0" required value={grader.maximum ?? 0} onChange={(event) => onChange({ maximum: Number(event.target.value) })} />;
  }
  if (grader.type === "run_status") {
    return <select aria-label={t("evaluation.expectedRunStatus")} value={grader.expected_status ?? "completed"} onChange={(event) => onChange({ expected_status: event.target.value as RunStatus })}><option value="completed">{displayStatus(t, "completed")}</option><option value="failed">{displayStatus(t, "failed")}</option><option value="cancelled">{displayStatus(t, "cancelled")}</option></select>;
  }
  return <span className="grader-no-config">{t("evaluation.noConfiguration")}</span>;
}

export function SuiteList({ suites, agents, onOpen, onOpenRun }: { suites: EvaluationSuiteSummary[]; agents: AgentDefinition[]; onOpen: (id: string) => void; onOpenRun: (id: string) => void }) {
  const { t } = useI18n();
  const formatRelativeTime = useRelativeTime();
  return <section className="surface recent-runs evaluation-suite-table"><div className="table-wrap"><table><thead><tr><th>{t("evaluation.suite")}</th><th>{t("evaluation.agent")}</th><th>{t("evaluation.cases")}</th><th>{t("evaluation.lastStatus")}</th><th>{t("evaluation.passRate")}</th><th>{t("evaluation.updated")}</th><th><span className="sr-only">{t("dashboard.recent.action")}</span></th></tr></thead><tbody>{suites.map((suite) => <tr key={suite.id}><td><button className="run-link" onClick={() => onOpen(suite.id)}>{suite.name}</button><small>{suite.description || t("evaluation.revisionFallback", { revision: suite.revision })}</small></td><td>{agents.find((agent) => agent.id === suite.agent_id)?.name ?? suite.agent_id.slice(0, 8)}</td><td>{suite.case_count}</td><td><button className={`eval-status ${suite.last_run_status ?? "idle"}`} disabled={!suite.last_run_id} onClick={() => suite.last_run_id && onOpenRun(suite.last_run_id)}>{statusLabel(t, suite.last_run_status)}</button></td><td>{formatEvaluationRate(suite.last_pass_rate)}</td><td>{formatRelativeTime(suite.updated_at)}</td><td><button className="icon-button" aria-label={t("evaluation.openSuite", { name: suite.name })} onClick={() => onOpen(suite.id)}><Icon name="chevron" /></button></td></tr>)}</tbody></table></div></section>;
}

export function EvaluationRunPanel({ run, results, filteredResults, filter, selectedResult, loading, onFilter, onSelect, onBack, onCancel, onViewRun }: { run: EvaluationRun; results: EvaluationCaseResult[]; filteredResults: EvaluationCaseResult[]; filter: ResultFilter; selectedResult: EvaluationCaseResult | null; loading: boolean; onFilter: (filter: ResultFilter) => void; onSelect: (id: string) => void; onBack: () => void; onCancel: () => void; onViewRun: (runId: string) => void }) {
  const { t } = useI18n();
  const metrics = [
    [t("runs.status"), statusLabel(t, run.status)], [t("evaluation.progress"), `${run.completed_cases} / ${run.total_cases}`], [t("evaluation.pass"), run.passed_cases], [t("evaluation.fail"), run.failed_cases], [t("evaluation.error"), run.error_cases], [t("evaluation.passRate"), formatEvaluationRate(run.pass_rate)], [t("evaluation.average"), run.average_duration_ms === null ? t("common.values.notAvailable") : `${Math.round(run.average_duration_ms)} ms`], ["p95", run.p95_duration_ms === null ? t("common.values.notAvailable") : `${Math.round(run.p95_duration_ms)} ms`],
  ];
  return <><PageHeader eyebrow={t("evaluation.runEyebrow")} title={t("evaluation.runTitle", { id: run.id.slice(0, 8) })} description={t("evaluation.runDescription", { revision: run.suite_revision })} action={<div className="button-row"><Button variant="ghost" onClick={onBack}>{t("common.actions.back")}</Button>{!terminalEvaluationStatuses.has(run.status) && <Button variant="danger" icon="close" onClick={onCancel}>{t("common.actions.cancel")}</Button>}</div>} />
    <section className="evaluation-summary" aria-label={t("evaluation.summaryAria")}>{metrics.map(([label, value]) => <article key={String(label)}><span>{label}</span><strong>{value}</strong></article>)}</section>
    <div className="evaluation-result-layout">
      <section className="surface evaluation-results"><div className="section-heading"><div><h2>{t("evaluation.caseResults")}</h2><p>{t("evaluation.linkedRuns", { count: results.length })}</p></div></div><div className="evaluation-filters" role="group" aria-label={t("evaluation.filtersAria")}>{(["all", "pass", "fail", "error"] as ResultFilter[]).map((value) => <button key={value} aria-pressed={filter === value} onClick={() => onFilter(value)}>{value === "all" ? t("trace.all") : statusLabel(t, value)}</button>)}</div>{loading && results.length === 0 ? <LoadingSkeleton rows={3} /> : filteredResults.length === 0 ? <p className="evaluation-empty-filter">{t("evaluation.noFilterMatches")}</p> : <div className="evaluation-result-list">{filteredResults.map((result) => <button key={result.id} className={selectedResult?.id === result.id ? "active" : ""} onClick={() => onSelect(result.id)}><span className={`eval-dot ${result.status ?? "idle"}`} /><div><strong>{snapshotName(result.case_snapshot, t)}</strong><small>{result.graders_passed} / {t("common.counts.graders", { count: result.graders_total })} · {result.duration_ms === null ? t("common.values.notAvailable") : `${Math.round(result.duration_ms)} ms`}</small></div><span className={`eval-status ${result.status ?? "idle"}`}>{statusLabel(t, result.status)}</span></button>)}</div>}</section>
      <CaseResultDetail result={selectedResult} onViewRun={onViewRun} />
    </div>
  </>;
}

function CaseResultDetail({ result, onViewRun }: { result: EvaluationCaseResult | null; onViewRun: (runId: string) => void }) {
  const { t } = useI18n();
  if (!result) return <section className="surface evaluation-case-detail"><EmptyState icon="evaluation" title={t("evaluation.selectCase")} description={t("evaluation.selectCaseDescription")} /></section>;
  return <section className="surface evaluation-case-detail"><header><div><span className={`eval-status ${result.status ?? "idle"}`}>{statusLabel(t, result.status)}</span><h2>{snapshotName(result.case_snapshot, t)}</h2></div>{result.run_id && <Button variant="secondary" icon="runs" onClick={() => onViewRun(result.run_id!)}>{t("evaluation.viewRunTrace")}</Button>}</header><dl className="case-facts"><div><dt>{t("evaluation.input")}</dt><dd>{String(result.case_snapshot.input ?? "")}</dd></div><div><dt>{t("evaluation.actualOutput")}</dt><dd>{result.actual_output ?? t("common.values.notAvailable")}</dd></div><div><dt>{t("evaluation.runStatus")}</dt><dd>{statusLabel(t, result.run_status)}</dd></div><div><dt>{t("runs.duration")}</dt><dd>{result.duration_ms === null ? t("common.values.notAvailable") : `${Math.round(result.duration_ms)} ms`}</dd></div></dl>{result.error && <div className="inline-error">{result.error}</div>}<div className="grader-results"><h3>{t("evaluation.graderResults")}</h3>{result.grader_results.map((grader) => <details key={grader.id} open={grader.outcome !== "pass"}><summary><span className={`eval-dot ${grader.outcome}`} /><strong>{graderLabel(grader.grader_type, t)}</strong><span className={`eval-status ${grader.outcome}`}>{statusLabel(t, grader.outcome)}</span></summary><p>{grader.message}</p><dl><div><dt>{t("evaluation.expected")}</dt><dd><code>{JSON.stringify(grader.expected)}</code></dd></div><div><dt>{t("evaluation.actual")}</dt><dd><code>{JSON.stringify(grader.actual)}</code></dd></div><div><dt>{t("evaluation.evidence")}</dt><dd>{grader.evidence.length ? grader.evidence.map((item, index) => <code key={index}>{JSON.stringify(item)}</code>) : t("evaluation.noEvidence")}</dd></div></dl></details>)}</div></section>;
}
