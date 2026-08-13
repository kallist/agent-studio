"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AgentBuilder } from "@/components/agent-builder";
import { AgentsPage } from "@/components/agents-page";
import { AppShell } from "@/components/app-shell";
import { Dashboard } from "@/components/dashboard";
import { KnowledgeStudio } from "@/components/knowledge-studio";
import { Playground } from "@/components/playground";
import { RunDetail } from "@/components/run-detail";
import { ConfirmDialog, ErrorBanner, ToastRegion } from "@/components/ui";
import { AgentDefinition, AgentEvent, api, eventTypes, KnowledgeBase, RunResult } from "@/lib/api";
import type { RunSnapshot, StudioView, ToastMessage } from "@/lib/studio-types";

const defaultInput = "Calculate 128 * 37 + 456";
const historyKey = "agent-studio.run-history.v1";
const views: StudioView[] = ["dashboard", "agents", "builder", "playground", "run"];

function createSnapshot(run: RunResult, events: AgentEvent[], agentName: string): RunSnapshot {
  const toolEvents = events.filter((event) => event.type === "tool.started");
  const latencies = events.map((event) => event.payload.latency_ms).filter((value): value is number => typeof value === "number");
  return { ...run, agentName, toolCalls: toolEvents.length, latencyMs: latencies.length ? latencies.reduce((sum, value) => sum + value, 0) : null };
}

export function Studio() {
  const [view, setView] = useState<StudioView>("dashboard");
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [run, setRun] = useState<RunResult | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [history, setHistory] = useState<RunSnapshot[]>([]);
  const [input, setInput] = useState(defaultInput);
  const [loading, setLoading] = useState(true);
  const [knowledgeLoading, setKnowledgeLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [knowledgeError, setKnowledgeError] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastMessage | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const streamRef = useRef<EventSource | null>(null);
  const agentsRef = useRef<AgentDefinition[]>([]);

  const selected = useMemo(() => agents.find((agent) => agent.id === selectedId) ?? null, [agents, selectedId]);

  useEffect(() => { agentsRef.current = agents; }, [agents]);

  const showToast = useCallback((tone: ToastMessage["tone"], title: string, message: string) => {
    setToast({ id: Date.now(), tone, title, message });
  }, []);

  const rememberRun = useCallback((latestRun: RunResult, latestEvents: AgentEvent[], fallbackName?: string) => {
    const agentName = agentsRef.current.find((agent) => agent.id === latestRun.agent_id)?.name ?? fallbackName ?? "Unknown agent";
    const snapshot = createSnapshot(latestRun, latestEvents, agentName);
    setHistory((current) => {
      const next = [snapshot, ...current.filter((item) => item.id !== snapshot.id)].slice(0, 30);
      window.localStorage.setItem(historyKey, JSON.stringify(next));
      return next;
    });
  }, []);

  const updateLocation = useCallback((nextView: StudioView, agentId?: string | null, runId?: string | null) => {
    const params = new URLSearchParams({ view: nextView });
    if (agentId) params.set("agent", agentId);
    if (runId) params.set("run", runId);
    window.history.replaceState(null, "", `?${params.toString()}`);
  }, []);

  const refreshRunState = useCallback(async (runId: string, notify = false) => {
    const [latestRun, latestEvents] = await Promise.all([api.getRun(runId), api.listEvents(runId)]);
    setRun(latestRun);
    setEvents(latestEvents);
    rememberRun(latestRun, latestEvents);
    if (notify) {
      if (latestRun.status === "completed") showToast("success", "Run completed", `${latestEvents.length} trace events were persisted.`);
      if (latestRun.status === "failed") showToast("error", "Run failed", latestRun.error ?? "The runtime returned an error.");
      if (latestRun.status === "cancelled") showToast("info", "Run cancelled", "The persisted trace remains available.");
    }
    return latestRun;
  }, [rememberRun, showToast]);

  const startStream = useCallback((runId: string, afterSequence = 0) => {
    streamRef.current?.close();
    const source = new EventSource(api.streamUrl(runId, afterSequence));
    streamRef.current = source;
    const onEvent = (message: MessageEvent<string>) => {
      let event: AgentEvent;
      try { event = JSON.parse(message.data) as AgentEvent; }
      catch { setError("A malformed trace event was ignored. Refresh the run to load persisted events."); return; }
      setEvents((current) => current.some((item) => item.event_id === event.event_id) ? current : [...current, event].sort((a, b) => a.sequence - b.sequence));
      if (event.type === "run.completed" || event.type === "run.failed" || event.type === "run.cancelled") {
        source.close();
        void refreshRunState(runId, true).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not refresh the run state."));
      }
    };
    eventTypes.forEach((type) => source.addEventListener(type, onEvent as EventListener));
    source.onerror = () => {
      source.close();
      void refreshRunState(runId).then((latestRun) => {
        if (latestRun.status !== "completed" && latestRun.status !== "failed" && latestRun.status !== "cancelled") {
          setError("The live trace connection was interrupted. Received events were preserved; retry the run when the API is available.");
        }
      }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not recover the run state."));
    };
  }, [refreshRunState]);

  const loadAgents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const loadedAgents = await api.listAgents();
      setAgents(loadedAgents);
      agentsRef.current = loadedAgents;
      setSelectedId((current) => loadedAgents.some((agent) => agent.id === current) ? current : loadedAgents[0]?.id ?? null);
      return loadedAgents;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Agent definitions could not be loaded.");
      return [];
    } finally { setLoading(false); }
  }, []);

  const loadKnowledgeBases = useCallback(async () => {
    setKnowledgeLoading(true);
    setKnowledgeError(null);
    try {
      const loadedBases = await api.listKnowledgeBases();
      setKnowledgeBases(loadedBases);
      return loadedBases;
    } catch (reason) {
      setKnowledgeError(reason instanceof Error ? reason.message : "Knowledge Bases could not be loaded.");
      return [];
    } finally { setKnowledgeLoading(false); }
  }, []);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const stored = window.localStorage.getItem(historyKey);
        if (stored) setHistory(JSON.parse(stored) as RunSnapshot[]);
      } catch { window.localStorage.removeItem(historyKey); }
      const [loadedAgents] = await Promise.all([loadAgents(), loadKnowledgeBases()]);
      if (!active) return;
      const params = new URLSearchParams(window.location.search);
      const requestedView = params.get("view");
      const agentId = params.get("agent");
      const runId = params.get("run");
      const initialAgent = loadedAgents.find((agent) => agent.id === agentId) ?? loadedAgents[0] ?? null;
      setSelectedId(initialAgent?.id ?? null);
      if (requestedView && views.includes(requestedView as StudioView)) setView(requestedView as StudioView);
      if (runId) {
        try {
          const [loadedRun, loadedEvents] = await Promise.all([api.getRun(runId), api.listEvents(runId)]);
          if (!active) return;
          setRun(loadedRun); setEvents(loadedEvents); setInput(loadedRun.input); setSelectedId(loadedRun.agent_id);
          rememberRun(loadedRun, loadedEvents, initialAgent?.name);
          if (loadedRun.status === "pending" || loadedRun.status === "running") startStream(runId, loadedEvents.at(-1)?.sequence ?? 0);
        } catch (reason) { if (active) setError(reason instanceof Error ? reason.message : "The requested run could not be loaded."); }
      }
    }
    void load();
    return () => { active = false; streamRef.current?.close(); };
  }, [loadAgents, loadKnowledgeBases, rememberRun, startStream]);

  const inspectRun = useCallback(async (snapshot: RunSnapshot) => {
    setError(null); setSubmitting(true);
    try {
      const [loadedRun, loadedEvents] = await Promise.all([api.getRun(snapshot.id), api.listEvents(snapshot.id)]);
      setRun(loadedRun); setEvents(loadedEvents); setInput(loadedRun.input); setSelectedId(loadedRun.agent_id); setView("run");
      updateLocation("run", loadedRun.agent_id, loadedRun.id); rememberRun(loadedRun, loadedEvents, snapshot.agentName);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "The selected run could not be loaded."); }
    finally { setSubmitting(false); }
  }, [rememberRun, updateLocation]);

  const navigate = useCallback((nextView: StudioView) => {
    if (nextView === "run" && !run && history[0]) {
      void inspectRun(history[0]);
      return;
    }
    setView(nextView);
    setError(null);
    updateLocation(nextView, selectedId, nextView === "run" || nextView === "playground" ? run?.id : null);
  }, [history, inspectRun, run, selectedId, updateLocation]);

  function selectAgent(agentId: string) {
    streamRef.current?.close();
    setSelectedId(agentId); setRun(null); setEvents([]); setError(null); setView("playground");
    updateLocation("playground", agentId);
  }

  async function createAgent(payload: Parameters<typeof api.createAgent>[0]): Promise<AgentDefinition | null> {
    setSubmitting(true); setError(null);
    try {
      const created = await api.createAgent(payload);
      setAgents((current) => [created, ...current]);
      setSelectedId(created.id); setRun(null); setEvents([]); setView("playground");
      updateLocation("playground", created.id);
      showToast("success", "Agent saved", `${created.name} is ready in the Playground.`);
      return created;
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "The agent definition could not be saved.";
      setError(message); showToast("error", "Save failed", message); return null;
    } finally { setSubmitting(false); }
  }

  async function runAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !input.trim()) return;
    setSubmitting(true); setError(null); setEvents([]); setRun(null);
    try {
      const createdRun = await api.createRun(selected.id, input.trim());
      setRun(createdRun); setView("playground"); updateLocation("playground", selected.id, createdRun.id); startStream(createdRun.id);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "The agent run could not be started.";
      setError(message); showToast("error", "Run could not start", message);
    } finally { setSubmitting(false); }
  }

  function clearRun() {
    streamRef.current?.close(); setRun(null); setEvents([]); setConfirmClear(false); updateLocation("playground", selectedId); showToast("info", "Conversation cleared", "The persisted run is still available from the Dashboard.");
  }

  function rerun() {
    if (run) setInput(run.input);
    setRun(null); setEvents([]); setView("playground"); updateLocation("playground", selectedId);
  }

  return (
    <AppShell view={view} hasRun={Boolean(run || history.length)} onNavigate={navigate}>
      {error && <ErrorBanner message={error} onRetry={() => void loadAgents()} onDismiss={() => setError(null)} />}
      {view === "dashboard" && <Dashboard agents={agents} runs={history} loading={loading} onNavigate={navigate} onInspectRun={(item) => void inspectRun(item)} />}
      {view === "agents" && <AgentsPage agents={agents} knowledgeBases={knowledgeBases} runs={history} loading={loading} selectedId={selectedId} onCreate={() => navigate("builder")} onOpen={(agent) => selectAgent(agent.id)} />}
      {view === "builder" && <><AgentBuilder saving={submitting} knowledgeBases={knowledgeBases} knowledgeLoading={knowledgeLoading} knowledgeError={knowledgeError} onReloadKnowledge={() => void loadKnowledgeBases()} onSave={createAgent} /><KnowledgeStudio bases={knowledgeBases} onBasesChange={(bases) => { setKnowledgeBases(bases); setKnowledgeError(null); }} /></>}
      {view === "playground" && <Playground agents={agents} selected={selected} run={run} events={events} input={input} submitting={submitting} onSelectAgent={selectAgent} onInput={setInput} onRun={runAgent} onBuild={() => navigate("builder")} onInspect={() => navigate("run")} onRequestClear={() => setConfirmClear(true)} />}
      {view === "run" && <RunDetail run={run} events={events} agent={selected} onBack={() => navigate("playground")} onRerun={rerun} />}
      <ToastRegion toast={toast} onDismiss={() => setToast(null)} />
      <ConfirmDialog open={confirmClear} title="Clear this conversation?" description="This removes the current conversation from the Playground. The persisted run remains available in recent runs." confirmLabel="Clear conversation" danger onConfirm={clearRun} onCancel={() => setConfirmClear(false)} />
    </AppShell>
  );
}
