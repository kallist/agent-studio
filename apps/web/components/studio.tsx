"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

import { TraceTimeline } from "@/components/trace-timeline";
import {
  AgentDefinition,
  AgentEvent,
  api,
  eventTypes,
  RunResult,
  RuntimeMode,
} from "@/lib/api";

const defaultInput = "计算 128 * 37 + 456";

export function Studio() {
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [run, setRun] = useState<RunResult | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [input, setInput] = useState(defaultInput);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const streamRef = useRef<EventSource | null>(null);

  const selected = useMemo(
    () => agents.find((agent) => agent.id === selectedId) ?? null,
    [agents, selectedId],
  );

  const updateLocation = useCallback((agentId: string, runId?: string) => {
    const params = new URLSearchParams({ agent: agentId });
    if (runId) params.set("run", runId);
    window.history.replaceState(null, "", `?${params.toString()}`);
  }, []);

  const startStream = useCallback((runId: string, afterSequence = 0) => {
    streamRef.current?.close();
    const source = new EventSource(api.streamUrl(runId, afterSequence));
    streamRef.current = source;

    const onEvent = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as AgentEvent;
      setEvents((current) => {
        if (current.some((item) => item.event_id === event.event_id)) return current;
        return [...current, event].sort((a, b) => a.sequence - b.sequence);
      });
      if (event.type === "run.completed" || event.type === "run.failed") {
        source.close();
        void api.getRun(runId).then(setRun).catch((reason: unknown) => {
          setError(reason instanceof Error ? reason.message : "无法刷新 run 状态。");
        });
      }
    };

    eventTypes.forEach((type) => source.addEventListener(type, onEvent as EventListener));
    source.onerror = () => {
      source.close();
      void Promise.all([api.getRun(runId), api.listEvents(runId)])
        .then(([latestRun, latestEvents]) => {
          setRun(latestRun);
          setEvents(latestEvents);
          if (latestRun.status !== "completed" && latestRun.status !== "failed") {
            setError("实时事件连接中断。已保留收到的 trace，请重试运行。");
          }
        })
        .catch((reason: unknown) => {
          setError(reason instanceof Error ? reason.message : "无法恢复 run 状态。");
        });
    };
  }, []);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const loadedAgents = await api.listAgents();
        if (!active) return;
        setAgents(loadedAgents);
        const params = new URLSearchParams(window.location.search);
        const agentId = params.get("agent");
        const runId = params.get("run");
        const initialAgent =
          loadedAgents.find((agent) => agent.id === agentId) ?? loadedAgents[0] ?? null;
        setSelectedId(initialAgent?.id ?? null);
        if (runId) {
          const [loadedRun, loadedEvents] = await Promise.all([
            api.getRun(runId),
            api.listEvents(runId),
          ]);
          if (!active) return;
          setRun(loadedRun);
          setEvents(loadedEvents);
          setInput(loadedRun.input);
          if (loadedRun.status === "pending" || loadedRun.status === "running") {
            startStream(runId, loadedEvents.at(-1)?.sequence ?? 0);
          }
        }
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : "加载 Agent Studio 失败。");
        }
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
      streamRef.current?.close();
    };
  }, [startStream]);

  function selectAgent(agentId: string) {
    setSelectedId(agentId);
    setRun(null);
    setEvents([]);
    setError(null);
    updateLocation(agentId);
  }

  async function createAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const data = new FormData(event.currentTarget);
    try {
      const created = await api.createAgent({
        name: String(data.get("name")),
        instructions: String(data.get("instructions")),
        runtime_mode: String(data.get("runtime_mode")) as RuntimeMode,
        tools: ["calculator"],
      });
      setAgents((current) => [created, ...current]);
      setSelectedId(created.id);
      setShowCreate(false);
      updateLocation(created.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建 Agent 失败。");
    } finally {
      setSubmitting(false);
    }
  }

  async function runAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    setSubmitting(true);
    setError(null);
    setEvents([]);
    setRun(null);
    try {
      const createdRun = await api.createRun(selected.id, input);
      setRun(createdRun);
      updateLocation(selected.id, createdRun.id);
      startStream(createdRun.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "运行 Agent 失败。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <Link className="brand" href="/" aria-label="Agent Studio home">
          <span className="brand-mark">AS</span>
          <span>
            <strong>Agent Studio</strong>
            <small>Observable agent development</small>
          </span>
        </Link>
        <div className="topbar-status">
          <span className="status-dot" /> Local workspace
        </div>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">RUNTIME WORKBENCH</p>
          <h1>Build agents you can actually inspect.</h1>
          <p className="hero-copy">
            Define an agent, run a real tool path, and follow every normalized event as it happens.
          </p>
        </div>
        <button className="primary-button" onClick={() => setShowCreate((value) => !value)}>
          {showCreate ? "关闭表单" : "创建 Agent"}
        </button>
      </section>

      {error && (
        <div className="error-banner" role="alert">
          <strong>Something needs attention</strong>
          <span>{error}</span>
          <button onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      {showCreate && (
        <form className="create-card" onSubmit={createAgent}>
          <div className="section-title">
            <span>01</span>
            <div><h2>New agent definition</h2><p>Saved to the backend database.</p></div>
          </div>
          <label>
            Name
            <input name="name" defaultValue="Calculator Agent" required maxLength={120} />
          </label>
          <label className="wide-field">
            Instructions
            <textarea
              name="instructions"
              defaultValue="Use the calculator tool for arithmetic and return the exact result."
              required
              rows={3}
            />
          </label>
          <label>
            Runtime mode
            <select name="runtime_mode" defaultValue="mock">
              <option value="mock">Mock / Demo · no API key</option>
              <option value="openai">OpenAI · opt-in credential</option>
            </select>
          </label>
          <div className="tool-field">
            <span>Enabled tool</span>
            <strong>✓ calculator</strong>
          </div>
          <button className="primary-button" disabled={submitting}>
            {submitting ? "保存中…" : "保存 Agent"}
          </button>
        </form>
      )}

      <div className="workspace-grid">
        <aside className="panel agent-panel">
          <div className="panel-header">
            <div><p className="eyebrow">DEFINITIONS</p><h2>Agents</h2></div>
            <span className="count-badge">{agents.length}</span>
          </div>
          {loading ? (
            <div className="skeleton-list" aria-label="Loading agents">
              <span /><span /><span />
            </div>
          ) : agents.length === 0 ? (
            <div className="empty-state"><strong>No agents yet</strong><p>Create the first definition to unlock the playground.</p></div>
          ) : (
            <div className="agent-list">
              {agents.map((agent) => (
                <button
                  key={agent.id}
                  className={agent.id === selectedId ? "agent-card selected" : "agent-card"}
                  onClick={() => selectAgent(agent.id)}
                >
                  <span className="agent-icon">ƒ</span>
                  <span className="agent-meta">
                    <strong>{agent.name}</strong>
                    <small>{agent.tools.join(", ")}</small>
                  </span>
                  <span className={`mode-pill ${agent.runtime_mode}`}>{agent.runtime_mode}</span>
                </button>
              ))}
            </div>
          )}
        </aside>

        <section className="panel playground-panel">
          <div className="panel-header">
            <div><p className="eyebrow">PLAYGROUND</p><h2>{selected?.name ?? "Select an agent"}</h2></div>
            {selected && <span className={`mode-pill ${selected.runtime_mode}`}>{selected.runtime_mode} runtime</span>}
          </div>
          {!selected ? (
            <div className="empty-state centered"><strong>Choose or create an agent</strong><p>The run console will appear here.</p></div>
          ) : (
            <>
              <div className="conversation" aria-live="polite">
                {run ? (
                  <>
                    <div className="message user-message"><span>YOU</span><p>{run.input}</p></div>
                    <div className="message agent-message">
                      <span>AGENT · {run.status}</span>
                      {run.status === "completed" && <p className="answer">{run.output}</p>}
                      {(run.status === "pending" || run.status === "running") && <p className="working">Running through {selected.runtime_mode} runtime…</p>}
                      {run.status === "failed" && <p className="run-error">{run.error}</p>}
                    </div>
                  </>
                ) : (
                  <div className="welcome-message">
                    <span className="agent-icon large">ƒ</span>
                    <strong>Ready to run</strong>
                    <p>This request will travel through the API, runtime port, tool executor, and persistence layer.</p>
                  </div>
                )}
              </div>
              <form className="composer" onSubmit={runAgent}>
                <label htmlFor="run-input">Message</label>
                <textarea
                  id="run-input"
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  rows={3}
                  required
                  disabled={submitting}
                />
                <div className="composer-footer">
                  <small>{selected.runtime_mode === "mock" ? "Deterministic demo · no API key" : "OpenAI credential required"}</small>
                  <button className="run-button" disabled={submitting || !input.trim()}>
                    {submitting ? "Starting…" : "Run agent →"}
                  </button>
                </div>
              </form>
            </>
          )}
        </section>

        <aside className="panel trace-panel">
          <div className="panel-header">
            <div><p className="eyebrow">LIVE TRACE</p><h2>Run events</h2></div>
            {run && <span className={`run-status ${run.status}`}>{run.status}</span>}
          </div>
          <TraceTimeline events={events} />
        </aside>
      </div>
    </main>
  );
}
