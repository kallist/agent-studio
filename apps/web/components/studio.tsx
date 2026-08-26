"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AgentBuilder } from "@/components/agent-builder";
import { AgentsPage } from "@/components/agents-page";
import { AppShell } from "@/components/app-shell";
import { Dashboard } from "@/components/dashboard";
import { EvaluationStudio } from "@/components/evaluation-studio";
import { KnowledgeStudio } from "@/components/knowledge-studio";
import { MemoryPanel } from "@/components/memory-panel";
import { Playground } from "@/components/playground";
import { RunDetail } from "@/components/run-detail";
import { ConfirmDialog, ErrorBanner, ToastRegion } from "@/components/ui";
import { AgentDefinition, AgentEvent, api, ApiConnectionStatus, DashboardObservability, KnowledgeBase, MemoryRecord, ProviderCatalogReadiness, reportApiConnection, RunObservability, RunResult, subscribeApiConnection } from "@/lib/api";
import type { RunSnapshot, StudioView, ToastMessage } from "@/lib/studio-types";
import { useI18n } from "@/i18n/provider";

const defaultInput = "Calculate 128 * 37 + 456";
const views: StudioView[] = ["dashboard", "agents", "builder", "playground", "evaluations", "run"];

export function Studio() {
  const { t } = useI18n();
  const [view, setView] = useState<StudioView>("dashboard");
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [run, setRun] = useState<RunResult | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [observability, setObservability] = useState<RunObservability | null>(null);
  const [telemetry, setTelemetry] = useState<DashboardObservability | null>(null);
  const [history, setHistory] = useState<RunSnapshot[]>([]);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [input, setInput] = useState(defaultInput);
  const [loading, setLoading] = useState(true);
  const [knowledgeLoading, setKnowledgeLoading] = useState(true);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memoryUpdating, setMemoryUpdating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [knowledgeError, setKnowledgeError] = useState<string | null>(null);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [apiStatus, setApiStatus] = useState<ApiConnectionStatus>("checking");
  const [providerReadiness, setProviderReadiness] = useState<ProviderCatalogReadiness | null>(null);
  const [toast, setToast] = useState<ToastMessage | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const streamRef = useRef<EventSource | null>(null);
  const agentsRef = useRef<AgentDefinition[]>([]);

  const selected = useMemo(() => agents.find((agent) => agent.id === selectedId) ?? null, [agents, selectedId]);

  useEffect(() => { agentsRef.current = agents; }, [agents]);
  useEffect(() => subscribeApiConnection(setApiStatus), []);

  const showToast = useCallback((tone: ToastMessage["tone"], title: string, message: string) => {
    setToast({ id: Date.now(), tone, title, message });
  }, []);

  const rememberRun = useCallback((summary: RunObservability, fallbackName?: string) => {
    const agentName = agentsRef.current.find((agent) => agent.id === summary.agent_id)?.name ?? fallbackName ?? t("agents.unknown");
    const snapshot: RunSnapshot = { ...summary, agentName };
    setHistory((current) => {
      return [snapshot, ...current.filter((item) => item.run_id !== snapshot.run_id)].slice(0, 30);
    });
  }, [t]);

  const refreshDashboard = useCallback(async () => {
    const data = await api.getDashboardObservability();
    setTelemetry(data);
    setHistory(data.recent_runs.map((summary) => ({
      ...summary,
      agentName: agentsRef.current.find((agent) => agent.id === summary.agent_id)?.name ?? t("agents.unknown"),
    })));
    return data;
  }, [t]);

  const updateLocation = useCallback((nextView: StudioView, agentId?: string | null, runId?: string | null) => {
    const params = new URLSearchParams({ view: nextView });
    if (agentId) params.set("agent", agentId);
    if (runId) params.set("run", runId);
    window.history.replaceState(null, "", `?${params.toString()}`);
  }, []);

  const loadMemories = useCallback(async (agentId: string) => {
    setMemoryLoading(true);
    setMemoryError(null);
    try { setMemories(await api.listMemories(agentId)); }
    catch (reason) { setMemoryError(reason instanceof Error ? reason.message : t("studioErrors.memoryLoad")); }
    finally { setMemoryLoading(false); }
  }, [t]);

  const refreshRunState = useCallback(async (runId: string, notify = false) => {
    const [latestRun, latestEvents, latestObservability] = await Promise.all([api.getRun(runId), api.listEvents(runId), api.getRunObservability(runId)]);
    setRun(latestRun);
    setEvents(latestEvents);
    setObservability(latestObservability);
    if (latestRun.run_kind === "normal") rememberRun(latestObservability);
    if (["completed", "failed", "cancelled"].includes(latestRun.status)) void refreshDashboard();
    await loadMemories(latestRun.agent_id);
    if (notify) {
      if (latestRun.status === "completed") showToast("success", t("notifications.runCompletedTitle"), t("notifications.runCompletedMessage", { count: latestEvents.length }));
      if (latestRun.status === "failed") showToast("error", t("notifications.runFailedTitle"), latestRun.error ?? t("notifications.runFailedMessage"));
      if (latestRun.status === "cancelled") showToast("info", t("notifications.runCancelledTitle"), t("notifications.runCancelledMessage"));
    }
    return latestRun;
  }, [loadMemories, refreshDashboard, rememberRun, showToast, t]);

  const startStream = useCallback((runId: string, afterSequence = 0) => {
    streamRef.current?.close();
    const source = new EventSource(api.streamUrl(runId, afterSequence));
    streamRef.current = source;
    source.onopen = () => reportApiConnection("connected");
    const onEvent = (message: MessageEvent<string>) => {
      let event: AgentEvent;
      try { event = JSON.parse(message.data) as AgentEvent; }
      catch { setError(t("studioErrors.malformedEvent")); return; }
      setEvents((current) => current.some((item) => item.event_id === event.event_id) ? current : [...current, event].sort((a, b) => a.sequence - b.sequence));
      if (["run.completed", "run.failed", "run.cancelled"].includes(event.type)) {
        source.close();
        void refreshRunState(runId, true).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : t("studioErrors.refreshRun")));
      }
    };
    source.addEventListener("agent.event", onEvent as EventListener);
    source.onerror = () => {
      reportApiConnection("offline");
      source.close();
      void refreshRunState(runId).then((latestRun) => {
        if (!["completed", "failed", "cancelled"].includes(latestRun.status)) setError(t("studioErrors.streamInterrupted"));
      }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : t("studioErrors.recoverRun")));
    };
  }, [refreshRunState, t]);

  const loadAgents = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const loadedAgents = await api.listAgents();
      setAgents(loadedAgents); agentsRef.current = loadedAgents;
      setSelectedId((current) => loadedAgents.some((agent) => agent.id === current) ? current : loadedAgents[0]?.id ?? null);
      return loadedAgents;
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("studioErrors.agentsLoad")); return []; }
    finally { setLoading(false); }
  }, [t]);

  const loadKnowledgeBases = useCallback(async () => {
    setKnowledgeLoading(true); setKnowledgeError(null);
    try { const loaded = await api.listKnowledgeBases(); setKnowledgeBases(loaded); return loaded; }
    catch (reason) { setKnowledgeError(reason instanceof Error ? reason.message : t("studioErrors.knowledgeLoad")); return []; }
    finally { setKnowledgeLoading(false); }
  }, [t]);

  useEffect(() => {
    let active = true;
    async function load() {
      void api.health().catch(() => undefined);
      const [loadedAgents, , readiness] = await Promise.all([
        loadAgents(),
        loadKnowledgeBases(),
        api.getProviderReadiness().catch(() => null),
      ]);
      if (!active) return;
      setProviderReadiness(readiness);
      await refreshDashboard().catch(() => undefined);
      const params = new URLSearchParams(window.location.search);
      const requestedView = params.get("view");
      const agentId = params.get("agent");
      const runId = params.get("run");
      const initialAgent = loadedAgents.find((agent) => agent.id === agentId) ?? loadedAgents[0] ?? null;
      setSelectedId(initialAgent?.id ?? null);
      if (initialAgent) void loadMemories(initialAgent.id);
      if (requestedView && views.includes(requestedView as StudioView)) setView(requestedView as StudioView);
      if (runId) {
        try {
          const [loadedRun, loadedEvents, loadedObservability] = await Promise.all([api.getRun(runId), api.listEvents(runId), api.getRunObservability(runId)]);
          if (!active) return;
          setRun(loadedRun); setEvents(loadedEvents); setObservability(loadedObservability); setInput(loadedRun.input); setSelectedId(loadedRun.agent_id);
          if (loadedRun.run_kind === "normal") rememberRun(loadedObservability, initialAgent?.name);
          if (["pending", "running"].includes(loadedRun.status)) startStream(runId, loadedEvents.at(-1)?.sequence ?? 0);
        } catch (reason) { if (active) setError(reason instanceof Error ? reason.message : t("studioErrors.requestedRun")); }
      }
    }
    void load();
    return () => { active = false; streamRef.current?.close(); };
  }, [loadAgents, loadKnowledgeBases, loadMemories, refreshDashboard, rememberRun, startStream, t]);

  const inspectRunId = useCallback(async (runId: string, fallbackName?: string) => {
    setError(null); setSubmitting(true);
    try {
      const [loadedRun, loadedEvents, loadedObservability] = await Promise.all([api.getRun(runId), api.listEvents(runId), api.getRunObservability(runId)]);
      setRun(loadedRun); setEvents(loadedEvents); setObservability(loadedObservability); setInput(loadedRun.input); setSelectedId(loadedRun.agent_id); setView("run");
      updateLocation("run", loadedRun.agent_id, loadedRun.id);
      if (loadedRun.run_kind === "normal") rememberRun(loadedObservability, fallbackName);
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("studioErrors.selectedRun")); }
    finally { setSubmitting(false); }
  }, [rememberRun, t, updateLocation]);

  const inspectRun = useCallback(async (snapshot: RunSnapshot) => {
    await inspectRunId(snapshot.run_id, snapshot.agentName);
  }, [inspectRunId]);

  const navigate = useCallback((nextView: StudioView) => {
    if (nextView === "run" && !run && history[0]) { void inspectRun(history[0]); return; }
    setView(nextView); setError(null);
    updateLocation(nextView, selectedId, nextView === "run" || nextView === "playground" ? run?.id : null);
  }, [history, inspectRun, run, selectedId, updateLocation]);

  function selectAgent(agentId: string) {
    streamRef.current?.close(); setSelectedId(agentId); setRun(null); setEvents([]); setObservability(null); setMemories([]); setError(null); setView("playground");
    updateLocation("playground", agentId); void loadMemories(agentId);
  }

  async function createAgent(payload: Parameters<typeof api.createAgent>[0]): Promise<AgentDefinition | null> {
    setSubmitting(true); setError(null);
    try {
      const created = await api.createAgent(payload);
      setAgents((current) => [created, ...current]); setSelectedId(created.id); setRun(null); setEvents([]); setObservability(null); setMemories([]); setView("playground");
      updateLocation("playground", created.id); showToast("success", t("notifications.agentSavedTitle"), t("notifications.agentSavedMessage", { name: created.name })); return created;
    } catch (reason) { const message = reason instanceof Error ? reason.message : t("studioErrors.saveAgent"); setError(message); showToast("error", t("notifications.saveFailedTitle"), message); return null; }
    finally { setSubmitting(false); }
  }

  async function toggleMemory(enabled: boolean) {
    if (!selected) return;
    setMemoryUpdating(true); setMemoryError(null);
    setAgents((current) => current.map((agent) => agent.id === selected.id ? { ...agent, memory_enabled: enabled } : agent));
    try {
      await api.setMemoryEnabled(selected.id, enabled);
      showToast("success", enabled ? t("notifications.memoryEnabledTitle") : t("notifications.memoryDisabledTitle"), enabled ? t("notifications.memoryEnabledMessage") : t("notifications.memoryDisabledMessage"));
    } catch (reason) {
      setAgents((current) => current.map((agent) => agent.id === selected.id ? { ...agent, memory_enabled: !enabled } : agent));
      setMemoryError(reason instanceof Error ? reason.message : t("studioErrors.memoryUpdate"));
    }
    finally { setMemoryUpdating(false); }
  }

  async function deleteMemory(memoryId: string) {
    if (!selected) return;
    setMemoryUpdating(true); setMemoryError(null);
    try { await api.deleteMemory(selected.id, memoryId); setMemories((current) => current.filter((memory) => memory.id !== memoryId)); showToast("info", t("notifications.memoryDeletedTitle"), t("notifications.memoryDeletedMessage")); }
    catch (reason) { setMemoryError(reason instanceof Error ? reason.message : t("studioErrors.memoryDelete")); }
    finally { setMemoryUpdating(false); }
  }

  async function runAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected || !input.trim()) return;
    setSubmitting(true); setError(null); setEvents([]); setRun(null); setObservability(null);
    try { const createdRun = await api.createRun(selected.id, input.trim()); setRun(createdRun); setView("playground"); updateLocation("playground", selected.id, createdRun.id); startStream(createdRun.id); }
    catch (reason) { const message = reason instanceof Error ? reason.message : t("studioErrors.runStart"); setError(message); showToast("error", t("notifications.runStartFailedTitle"), message); }
    finally { setSubmitting(false); }
  }

  async function cancelRun() { if (!run) return; try { await api.cancelRun(run.id); showToast("info", t("notifications.cancellationTitle"), t("notifications.cancellationMessage")); } catch (reason) { setError(reason instanceof Error ? reason.message : t("studioErrors.runCancel")); } }
  function clearRun() { streamRef.current?.close(); setRun(null); setEvents([]); setObservability(null); setConfirmClear(false); updateLocation("playground", selectedId); showToast("info", t("notifications.clearedTitle"), t("notifications.clearedMessage")); }
  function rerun() { if (run) setInput(run.input); setRun(null); setEvents([]); setObservability(null); setView("playground"); updateLocation("playground", selectedId); }

  return (
    <AppShell view={view} hasRun={Boolean(run || history.length)} apiStatus={apiStatus} onNavigate={navigate}>
      {error && <ErrorBanner message={error} onRetry={() => void loadAgents()} onDismiss={() => setError(null)} />}
      {view === "dashboard" && <Dashboard agents={agents} telemetry={telemetry} runs={history} loading={loading} onNavigate={navigate} onInspectRun={(item) => void inspectRun(item)} />}
      {view === "agents" && <AgentsPage agents={agents} knowledgeBases={knowledgeBases} runs={history} loading={loading} selectedId={selectedId} onCreate={() => navigate("builder")} onOpen={(agent) => selectAgent(agent.id)} />}
      {view === "builder" && <><AgentBuilder saving={submitting} providerReadiness={providerReadiness} knowledgeBases={knowledgeBases} knowledgeLoading={knowledgeLoading} knowledgeError={knowledgeError} onReloadKnowledge={() => void loadKnowledgeBases()} onSave={createAgent} /><KnowledgeStudio bases={knowledgeBases} onBasesChange={(bases) => { setKnowledgeBases(bases); setKnowledgeError(null); }} /></>}
      {view === "playground" && <><Playground agents={agents} selected={selected} run={run} events={events} input={input} submitting={submitting} onSelectAgent={selectAgent} onInput={setInput} onRun={runAgent} onCancel={() => void cancelRun()} onBuild={() => navigate("builder")} onInspect={() => navigate("run")} onRequestClear={() => setConfirmClear(true)} />{selected && <MemoryPanel enabled={selected.memory_enabled} loading={memoryLoading} updating={memoryUpdating} error={memoryError} memories={memories} onDelete={(memoryId) => void deleteMemory(memoryId)} onToggle={(enabled) => void toggleMemory(enabled)} />}</>}
      {view === "evaluations" && <EvaluationStudio agents={agents} onViewRun={(runId) => void inspectRunId(runId)} />}
      {view === "run" && <RunDetail run={run} events={events} observability={observability} agent={selected} onBack={() => navigate(run?.run_kind === "evaluation" ? "evaluations" : "playground")} onRerun={rerun} />}
      <ToastRegion toast={toast} onDismiss={() => setToast(null)} />
      <ConfirmDialog open={confirmClear} title={t("playground.clearTitle")} description={t("playground.clearDescription")} confirmLabel={t("playground.clearConfirm")} danger onConfirm={clearRun} onCancel={() => setConfirmClear(false)} />
    </AppShell>
  );
}
