export type RuntimeMode = "mock" | "openai";
export type RunStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type EventType =
  | "run.started"
  | "step.started"
  | "llm.started"
  | "llm.retrying"
  | "llm.completed"
  | "tool.selected"
  | "tool.started"
  | "tool.completed"
  | "tool.failed"
  | "step.completed"
  | "run.completed"
  | "run.failed"
  | "run.cancelled";

export interface AgentDefinition {
  id: string;
  name: string;
  instructions: string;
  runtime_mode: RuntimeMode;
  model: string | null;
  tools: string[];
  created_at: string;
}

export interface RunResult {
  id: string;
  agent_id: string;
  status: RunStatus;
  input: string;
  output: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentEvent {
  event_id: string;
  run_id: string;
  sequence: number;
  type: EventType;
  timestamp: string;
  payload: Record<string, unknown>;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new Error("无法连接 Agent Studio API。请确认后端已在 8000 端口运行。");
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `API 请求失败 (${response.status})`);
  }
  return (await response.json()) as T;
}

export const api = {
  listAgents: () => request<AgentDefinition[]>("/agents"),
  createAgent: (payload: {
    name: string;
    instructions: string;
    runtime_mode: RuntimeMode;
    tools: string[];
  }) => request<AgentDefinition>("/agents", { method: "POST", body: JSON.stringify(payload) }),
  createRun: (agentId: string, input: string) =>
    request<RunResult>(`/agents/${agentId}/runs`, {
      method: "POST",
      body: JSON.stringify({ input }),
    }),
  getRun: (runId: string) => request<RunResult>(`/runs/${runId}`),
  listEvents: (runId: string) => request<AgentEvent[]>(`/runs/${runId}/events`),
  streamUrl: (runId: string, afterSequence = 0) =>
    `${API_URL}/runs/${runId}/stream?after_sequence=${afterSequence}`,
};

export const eventTypes: EventType[] = [
  "run.started",
  "step.started",
  "llm.started",
  "llm.retrying",
  "llm.completed",
  "tool.selected",
  "tool.started",
  "tool.completed",
  "tool.failed",
  "step.completed",
  "run.completed",
  "run.failed",
  "run.cancelled",
];
