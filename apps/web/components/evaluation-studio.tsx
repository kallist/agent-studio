"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { Icon } from "@/components/icons";
import { Button, EmptyState, LoadingSkeleton, PageHeader, formatRelativeTime } from "@/components/ui";
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

const graderTypes: Array<{ value: GraderType; label: string }> = [
  { value: "run_status", label: "Run status" },
  { value: "final_output_non_empty", label: "Final output non-empty" },
  { value: "exact_match", label: "Exact match" },
  { value: "contains", label: "Contains" },
  { value: "tool_selected", label: "Tool selected" },
  { value: "tool_not_selected", label: "Tool not selected" },
  { value: "retrieval_hit", label: "Retrieval hit" },
  { value: "citation", label: "Citation" },
  { value: "memory_retrieved", label: "Memory retrieved" },
  { value: "max_steps", label: "Maximum steps" },
  { value: "max_duration", label: "Maximum duration" },
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

function statusLabel(status: string | null): string {
  return status ? status.toUpperCase() : "PENDING";
}

function snapshotName(snapshot: Record<string, unknown>): string {
  return typeof snapshot.name === "string" ? snapshot.name : "Evaluation case";
}

function graderLabel(type: GraderType): string {
  return graderTypes.find((item) => item.value === type)?.label ?? type;
}

export function EvaluationStudio({
  agents,
  onViewRun,
}: {
  agents: AgentDefinition[];
  onViewRun: (runId: string) => void;
}) {
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
      setError(reason instanceof Error ? reason.message : "Evaluation suites could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

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
        setError(reason instanceof Error ? reason.message : "The evaluation run could not be refreshed.");
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
  }, [activeEvaluationRunId, loadSuites, pollRevision]);

  const openSuite = useCallback(async (suiteId: string) => {
    setLoading(true);
    setError(null);
    try {
      const loaded = await api.getEvaluationSuite(suiteId);
      setSuite(loaded);
      setScreen("suite");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The evaluation suite could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

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
      setError(reason instanceof Error ? reason.message : "The evaluation suite could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function deleteSuite() {
    if (!suite || !window.confirm(`Delete ${suite.name}? Historical evaluation runs remain available by direct link.`)) return;
    setSaving(true);
    try {
      await api.deleteEvaluationSuite(suite.id);
      setSuite(null);
      setScreen("list");
      await loadSuites();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The evaluation suite could not be deleted.");
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
      setError(reason instanceof Error ? reason.message : "The evaluation run could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

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
      setError(reason instanceof Error ? reason.message : "The evaluation run could not be started.");
      setSaving(false);
    }
  }

  async function cancelEvaluation() {
    if (!evaluationRun) return;
    try {
      setEvaluationRun(await api.cancelEvaluationRun(evaluationRun.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The evaluation could not be cancelled.");
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
        <PageHeader eyebrow="Evaluations" title={suite ? "Edit evaluation suite" : "Create evaluation suite"} description="Define deterministic expectations for real Agent Studio executions." action={<Button type="button" variant="ghost" onClick={() => setScreen(suite ? "suite" : "list")}>Cancel</Button>} />
        {error && <div className="inline-error" role="alert">{error}</div>}
        <section className="surface evaluation-form-section">
          <div className="field-grid">
            <label><span>Suite name</span><input required value={name} onChange={(event) => setName(event.target.value)} placeholder="Calculator Regression" /></label>
            <label><span>Agent</span><select required value={agentId} onChange={(event) => setAgentId(event.target.value)}><option value="">Select an agent</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label>
          </div>
          <label><span>Description</span><textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What behavior this suite protects" /></label>
        </section>
        <section className="evaluation-cases" aria-label="Evaluation cases">
          <div className="section-heading"><div><h2>Cases</h2><p>Each case launches an isolated real agent run.</p></div><Button type="button" variant="secondary" icon="plus" onClick={() => setDraftCases((current) => [...current, newCase()])}>Add case</Button></div>
          {draftCases.map((item, caseIndex) => (
            <article className="surface evaluation-case-editor" key={item.clientId}>
              <header><div><small>Case {caseIndex + 1}</small><h3>{item.name || "Untitled case"}</h3></div><button type="button" className="icon-button danger" aria-label={`Delete case ${caseIndex + 1}`} disabled={draftCases.length === 1} onClick={() => setDraftCases((current) => current.filter((candidate) => candidate.clientId !== item.clientId))}><Icon name="trash" /></button></header>
              <div className="field-grid">
                <label><span>Case name</span><input required value={item.name} onChange={(event) => updateCase(item.clientId, { name: event.target.value })} /></label>
                <label className="checkbox-field"><input type="checkbox" checked={item.enabled} onChange={(event) => updateCase(item.clientId, { enabled: event.target.checked })} /><span>Enabled</span></label>
              </div>
              <label><span>Input</span><textarea required value={item.input} onChange={(event) => updateCase(item.clientId, { input: event.target.value })} /></label>
              <label><span>Evaluation-only Memory seed <small>Optional; isolated per case</small></span><textarea value={item.memorySeed} onChange={(event) => updateCase(item.clientId, { memorySeed: event.target.value })} placeholder="The project codename is Aurora" /></label>
              <div className="grader-list">
                <div className="grader-heading"><strong>Graders</strong><button type="button" onClick={() => updateCase(item.clientId, { graders: [...item.graders, newGrader()] })}><Icon name="plus" /> Add grader</button></div>
                {item.graders.map((grader, graderIndex) => (
                  <div className="grader-config" key={`${item.clientId}-${graderIndex}`}>
                    <select aria-label={`Grader ${graderIndex + 1} type`} value={grader.type} onChange={(event) => updateGrader(item.clientId, graderIndex, newGrader(event.target.value as GraderType))}>{graderTypes.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}</select>
                    <GraderFields grader={grader} onChange={(update) => updateGrader(item.clientId, graderIndex, update)} />
                    <label className="required-check"><input type="checkbox" checked={grader.required} onChange={(event) => updateGrader(item.clientId, graderIndex, { required: event.target.checked })} /> Required</label>
                    <button type="button" className="icon-button" aria-label={`Delete grader ${graderIndex + 1}`} disabled={item.graders.length === 1} onClick={() => updateCase(item.clientId, { graders: item.graders.filter((_candidate, index) => index !== graderIndex) })}><Icon name="trash" /></button>
                  </div>
                ))}
              </div>
            </article>
          ))}
        </section>
        <div className="form-actions"><Button type="button" variant="ghost" onClick={() => setScreen(suite ? "suite" : "list")}>Cancel</Button><Button type="submit" icon="check" disabled={saving || !agents.length}>{saving ? "Saving…" : "Save suite"}</Button></div>
      </form>
    );
  }

  if (screen === "suite" && suite) {
    return (
      <>
        <PageHeader eyebrow="Evaluation suite" title={suite.name} description={suite.description || "Deterministic expectations executed through the real agent runtime."} action={<div className="button-row"><Button variant="ghost" onClick={() => setScreen("list")}>All suites</Button><Button variant="secondary" icon="builder" onClick={() => openBuilder(suite)}>Edit</Button><Button icon="play" disabled={saving || suite.cases.filter((item) => item.enabled).length === 0} onClick={() => void runEvaluation()}>{saving ? "Starting…" : "Run evaluation"}</Button></div>} />
        {error && <div className="inline-error" role="alert">{error}</div>}
        <section className="evaluation-suite-meta surface"><div><span>Revision</span><strong>{suite.revision}</strong></div><div><span>Cases</span><strong>{suite.cases.length}</strong></div><div><span>Agent</span><strong>{agents.find((agent) => agent.id === suite.agent_id)?.name ?? suite.agent_id.slice(0, 8)}</strong></div><button className="text-danger" disabled={saving} onClick={() => void deleteSuite()}>Delete suite</button></section>
        <section className="surface evaluation-case-list"><div className="section-heading"><div><h2>Cases</h2><p>Definitions are snapshotted when a run starts.</p></div></div>{suite.cases.map((item) => <article key={item.id}><span className={`eval-dot ${item.enabled ? "pass" : "idle"}`} /><div><strong>{item.name}</strong><p>{item.input}</p><small>{item.graders.length} graders · {item.setup.memories.length ? "isolated Memory setup" : "no setup"}</small></div><span>{item.enabled ? "Enabled" : "Disabled"}</span></article>)}</section>
      </>
    );
  }

  if (screen === "run" && evaluationRun) {
    return (
      <>
        {error && <div className="inline-error" role="alert"><span>{error}</span><Button variant="ghost" onClick={retryEvaluationRefresh}>Retry refresh</Button></div>}
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
      <PageHeader eyebrow="Quality" title="Evaluations" description="Was the agent behavior good? Run deterministic regression suites against real persisted executions." action={<Button icon="plus" disabled={!agents.length} onClick={() => openBuilder()}>Create suite</Button>} />
      {error && <div className="inline-error" role="alert">{error}</div>}
      {loading ? <LoadingSkeleton rows={4} /> : suites.length === 0 ? <EmptyState icon="evaluation" title="No evaluation suites" description="Create a suite to evaluate final answers, tool selection, RAG, Memory, steps, and latency." action={<Button icon="plus" disabled={!agents.length} onClick={() => openBuilder()}>Create suite</Button>} /> : <SuiteList suites={suites} agents={agents} onOpen={(id) => void openSuite(id)} onOpenRun={(id) => void openEvaluationRun(id)} />}
    </>
  );
}

function GraderFields({ grader, onChange }: { grader: GraderConfig; onChange: (update: Partial<GraderConfig>) => void }) {
  if (grader.type === "exact_match" || grader.type === "contains") {
    return <><input aria-label="Expected text" required value={grader.value ?? ""} onChange={(event) => onChange({ value: event.target.value })} placeholder="Expected text" /><label className="required-check"><input type="checkbox" checked={grader.case_sensitive} onChange={(event) => onChange({ case_sensitive: event.target.checked })} /> Case-sensitive</label></>;
  }
  if (grader.type === "tool_selected" || grader.type === "tool_not_selected") {
    return <input aria-label="Tool name" required value={grader.tool_name ?? ""} onChange={(event) => onChange({ tool_name: event.target.value })} placeholder="calculator" />;
  }
  if (grader.type === "retrieval_hit" || grader.type === "citation") {
    return <input aria-label="Expected source" value={grader.expected_source ?? ""} onChange={(event) => onChange({ expected_source: event.target.value || null })} placeholder="upload://source.md (optional)" />;
  }
  if (grader.type === "max_steps" || grader.type === "max_duration") {
    return <input aria-label={grader.type === "max_steps" ? "Maximum steps" : "Maximum duration ms"} type="number" min="0" required value={grader.maximum ?? 0} onChange={(event) => onChange({ maximum: Number(event.target.value) })} />;
  }
  if (grader.type === "run_status") {
    return <select aria-label="Expected run status" value={grader.expected_status ?? "completed"} onChange={(event) => onChange({ expected_status: event.target.value as RunStatus })}><option value="completed">Completed</option><option value="failed">Failed</option><option value="cancelled">Cancelled</option></select>;
  }
  return <span className="grader-no-config">No configuration</span>;
}

export function SuiteList({ suites, agents, onOpen, onOpenRun }: { suites: EvaluationSuiteSummary[]; agents: AgentDefinition[]; onOpen: (id: string) => void; onOpenRun: (id: string) => void }) {
  return <section className="surface recent-runs evaluation-suite-table"><div className="table-wrap"><table><thead><tr><th>Suite</th><th>Agent</th><th>Cases</th><th>Last status</th><th>Pass rate</th><th>Updated</th><th><span className="sr-only">Action</span></th></tr></thead><tbody>{suites.map((suite) => <tr key={suite.id}><td><button className="run-link" onClick={() => onOpen(suite.id)}>{suite.name}</button><small>{suite.description || `Revision ${suite.revision}`}</small></td><td>{agents.find((agent) => agent.id === suite.agent_id)?.name ?? suite.agent_id.slice(0, 8)}</td><td>{suite.case_count}</td><td><button className={`eval-status ${suite.last_run_status ?? "idle"}`} disabled={!suite.last_run_id} onClick={() => suite.last_run_id && onOpenRun(suite.last_run_id)}>{statusLabel(suite.last_run_status)}</button></td><td>{formatEvaluationRate(suite.last_pass_rate)}</td><td>{formatRelativeTime(suite.updated_at)}</td><td><button className="icon-button" aria-label={`Open ${suite.name}`} onClick={() => onOpen(suite.id)}><Icon name="chevron" /></button></td></tr>)}</tbody></table></div></section>;
}

export function EvaluationRunPanel({ run, results, filteredResults, filter, selectedResult, loading, onFilter, onSelect, onBack, onCancel, onViewRun }: { run: EvaluationRun; results: EvaluationCaseResult[]; filteredResults: EvaluationCaseResult[]; filter: ResultFilter; selectedResult: EvaluationCaseResult | null; loading: boolean; onFilter: (filter: ResultFilter) => void; onSelect: (id: string) => void; onBack: () => void; onCancel: () => void; onViewRun: (runId: string) => void }) {
  const metrics = [
    ["Status", statusLabel(run.status)],
    ["Progress", `${run.completed_cases} / ${run.total_cases}`],
    ["Pass", run.passed_cases],
    ["Fail", run.failed_cases],
    ["Error", run.error_cases],
    ["Pass rate", formatEvaluationRate(run.pass_rate)],
    ["Average", run.average_duration_ms === null ? "N/A" : `${Math.round(run.average_duration_ms)} ms`],
    ["p95", run.p95_duration_ms === null ? "N/A" : `${Math.round(run.p95_duration_ms)} ms`],
  ];
  return <><PageHeader eyebrow="Evaluation run" title={`Run ${run.id.slice(0, 8)}`} description={`Suite revision ${run.suite_revision} · deterministic offline graders`} action={<div className="button-row"><Button variant="ghost" onClick={onBack}>Back</Button>{!terminalEvaluationStatuses.has(run.status) && <Button variant="danger" icon="close" onClick={onCancel}>Cancel</Button>}</div>} />
    <section className="evaluation-summary" aria-label="Evaluation summary">{metrics.map(([label, value]) => <article key={String(label)}><span>{label}</span><strong>{value}</strong></article>)}</section>
    <div className="evaluation-result-layout">
      <section className="surface evaluation-results"><div className="section-heading"><div><h2>Case results</h2><p>{results.length} real Agent runs linked to persisted traces.</p></div></div><div className="evaluation-filters" role="group" aria-label="Case result filters">{(["all", "pass", "fail", "error"] as ResultFilter[]).map((value) => <button key={value} aria-pressed={filter === value} onClick={() => onFilter(value)}>{value === "all" ? "All" : statusLabel(value)}</button>)}</div>{loading && results.length === 0 ? <LoadingSkeleton rows={3} /> : filteredResults.length === 0 ? <p className="evaluation-empty-filter">No cases match this filter.</p> : <div className="evaluation-result-list">{filteredResults.map((result) => <button key={result.id} className={selectedResult?.id === result.id ? "active" : ""} onClick={() => onSelect(result.id)}><span className={`eval-dot ${result.status ?? "idle"}`} /><div><strong>{snapshotName(result.case_snapshot)}</strong><small>{result.graders_passed} / {result.graders_total} graders · {result.duration_ms === null ? "N/A" : `${Math.round(result.duration_ms)} ms`}</small></div><span className={`eval-status ${result.status ?? "idle"}`}>{statusLabel(result.status)}</span></button>)}</div>}</section>
      <CaseResultDetail result={selectedResult} onViewRun={onViewRun} />
    </div>
  </>;
}

function CaseResultDetail({ result, onViewRun }: { result: EvaluationCaseResult | null; onViewRun: (runId: string) => void }) {
  if (!result) return <section className="surface evaluation-case-detail"><EmptyState icon="evaluation" title="Select a case" description="Choose a result to inspect actual output and grader evidence." /></section>;
  return <section className="surface evaluation-case-detail"><header><div><span className={`eval-status ${result.status ?? "idle"}`}>{statusLabel(result.status)}</span><h2>{snapshotName(result.case_snapshot)}</h2></div>{result.run_id && <Button variant="secondary" icon="runs" onClick={() => onViewRun(result.run_id!)}>View Run Trace</Button>}</header><dl className="case-facts"><div><dt>Input</dt><dd>{String(result.case_snapshot.input ?? "")}</dd></div><div><dt>Actual final output</dt><dd>{result.actual_output ?? "N/A"}</dd></div><div><dt>Run status</dt><dd>{statusLabel(result.run_status)}</dd></div><div><dt>Duration</dt><dd>{result.duration_ms === null ? "N/A" : `${Math.round(result.duration_ms)} ms`}</dd></div></dl>{result.error && <div className="inline-error">{result.error}</div>}<div className="grader-results"><h3>Grader results</h3>{result.grader_results.map((grader) => <details key={grader.id} open={grader.outcome !== "pass"}><summary><span className={`eval-dot ${grader.outcome}`} /><strong>{graderLabel(grader.grader_type)}</strong><span className={`eval-status ${grader.outcome}`}>{statusLabel(grader.outcome)}</span></summary><p>{grader.message}</p><dl><div><dt>Expected</dt><dd><code>{JSON.stringify(grader.expected)}</code></dd></div><div><dt>Actual</dt><dd><code>{JSON.stringify(grader.actual)}</code></dd></div><div><dt>Evidence</dt><dd>{grader.evidence.length ? grader.evidence.map((item, index) => <code key={index}>{JSON.stringify(item)}</code>) : "None"}</dd></div></dl></details>)}</div></section>;
}
