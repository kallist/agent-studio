export type RuntimeMode = "mock" | "openai";
export type RunStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type KnownEventType =
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
  | "memory.retrieved"
  | "memory.retrieval.skipped"
  | "memory.written"
  | "run.completed"
  | "run.failed"
  | "run.cancelled";
export type EventType = KnownEventType | (string & {});

export interface AgentDefinition {
  id: string;
  name: string;
  instructions: string;
  runtime_mode: RuntimeMode;
  model: string | null;
  tools: string[];
  knowledge_base_ids: string[];
  memory_enabled: boolean;
  created_at: string;
}

export interface MemoryRecord {
  id: string;
  agent_id: string;
  kind: "conversation" | "working" | "long_term";
  content: string;
  importance: number;
  source_run_id: string | null;
  created_at: string;
  expires_at: string | null;
  metadata: Record<string, unknown>;
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
  step_index?: number | null;
  tool_call_id?: string | null;
  duration_ms?: number | null;
  usage?: UsageMetrics | null;
  payload: Record<string, unknown>;
}

export interface UsageMetrics {
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
}

export interface ToolCallObservation {
  tool_call_id: string;
  tool_name: string;
  step_index: number | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  status: "running" | "completed" | "failed" | "unknown";
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  error_summary: string | null;
}

export interface RunObservability {
  run_id: string;
  agent_id: string;
  runtime_type: string | null;
  provider_type: string | null;
  status: RunStatus;
  termination_reason: string | null;
  created_at: string;
  started_at: string | null;
  terminal_at: string | null;
  duration_ms: number | null;
  event_count: number;
  step_count: number;
  tool_calls: { total: number; succeeded: number; failed: number };
  usage: UsageMetrics;
  error_category: string | null;
  error_summary: string | null;
  event_statistics: Record<string, number>;
  tools: ToolCallObservation[];
}

export interface DashboardObservability {
  total_runs: number;
  completed: number;
  failed: number;
  cancelled: number;
  running: number;
  success_rate: number | null;
  average_duration_ms: number | null;
  recent_runs: RunObservability[];
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export type ApiConnectionStatus = "checking" | "connected" | "offline";

let connectionStatus: ApiConnectionStatus = "checking";
const connectionListeners = new Set<(status: ApiConnectionStatus) => void>();

export function reportApiConnection(status: ApiConnectionStatus): void {
  if (connectionStatus === status) return;
  connectionStatus = status;
  connectionListeners.forEach((listener) => listener(status));
}

export function subscribeApiConnection(listener: (status: ApiConnectionStatus) => void): () => void {
  listener(connectionStatus);
  connectionListeners.add(listener);
  return () => connectionListeners.delete(listener);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
    });
  } catch {
    reportApiConnection("offline");
    throw new Error("Cannot connect to the Agent Studio API. Confirm that the backend is running on port 8000.");
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    // A 4xx response proves the API is reachable; a 5xx response makes the
    // current health indicator unhealthy regardless of whether its body parses.
    reportApiConnection(response.status < 500 ? "connected" : "offline");
    throw new Error(body?.detail ?? `API request failed (${response.status}).`);
  }
  reportApiConnection("connected");
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  listAgents: () => request<AgentDefinition[]>("/agents"),
  createAgent: (payload: {
    name: string;
    instructions: string;
    runtime_mode: RuntimeMode;
    model: string | null;
    tools: string[];
    knowledge_base_ids?: string[];
    memory_enabled?: boolean;
  }) => request<AgentDefinition>("/agents", { method: "POST", body: JSON.stringify(payload) }),
  createRun: (agentId: string, input: string) =>
    request<RunResult>(`/agents/${agentId}/runs`, {
      method: "POST",
      body: JSON.stringify({ input }),
    }),
  getRun: (runId: string) => request<RunResult>(`/runs/${runId}`),
  cancelRun: (runId: string) => request<RunResult>(`/runs/${runId}/cancel`, { method: "POST" }),
  listEvents: (runId: string) => request<AgentEvent[]>(`/runs/${runId}/events`),
  getRunObservability: (runId: string) =>
    request<RunObservability>(`/runs/${runId}/observability`),
  getDashboardObservability: () =>
    request<DashboardObservability>("/observability/dashboard"),
  listMemories: (agentId: string) =>
    request<MemoryRecord[]>(`/agents/${agentId}/memories`),
  setMemoryEnabled: (agentId: string, enabled: boolean) =>
    request<{ agent_id: string; enabled: boolean }>(`/agents/${agentId}/memory-settings`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }),
  deleteMemory: (agentId: string, memoryId: string) =>
    request<void>(`/agents/${agentId}/memories/${memoryId}`, { method: "DELETE" }),
  streamUrl: (runId: string, afterSequence = 0) =>
    `${API_URL}/runs/${runId}/stream?after_sequence=${afterSequence}`,
  listKnowledgeBases: () => request<KnowledgeBase[]>("/knowledge-bases"),
  createKnowledgeBase: (name: string, description: string) =>
    request<KnowledgeBase>("/knowledge-bases", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),
  listDocuments: (knowledgeBaseId: string) =>
    request<KnowledgeDocument[]>(`/knowledge-bases/${knowledgeBaseId}/documents`),
  uploadDocument: (knowledgeBaseId: string, file: File) => {
    const data = new FormData();
    data.set("file", file);
    return request<DocumentUploadAccepted>(`/knowledge-bases/${knowledgeBaseId}/documents`, {
      method: "POST",
      body: data,
    });
  },
  getIngestionJob: (jobId: string) => request<IngestionJob>(`/ingestion-jobs/${jobId}`),
  searchKnowledge: (knowledgeBaseId: string, query: string, topK = 5) =>
    request<KnowledgeSearchResponse>(`/knowledge-bases/${knowledgeBaseId}/search`, {
      method: "POST",
      body: JSON.stringify({ query, top_k: topK, hybrid: true }),
    }),
};

export type IngestionState = "queued" | "processing" | "completed" | "failed";

export interface KnowledgeBase {
  id: string;
  name: string;
  description: string;
  embedding_provider: string;
  embedding_model: string;
  created_at: string;
  document_count: number;
}

export interface IngestionJob {
  id: string;
  document_id: string;
  state: IngestionState;
  error: string | null;
  queued_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface KnowledgeDocument {
  id: string;
  knowledge_base_id: string;
  filename: string;
  source: string;
  mime_type: string;
  size_bytes: number;
  created_at: string;
  ingestion: IngestionJob | null;
}

export interface DocumentUploadAccepted {
  document: KnowledgeDocument;
  ingestion_job: IngestionJob;
}

export interface KnowledgeCitation {
  document_id: string;
  document: string;
  chunk_id: string;
  chunk_index: number;
  source: string;
  score: number;
  content: string;
  metadata: Record<string, unknown>;
}

export interface KnowledgeSearchResponse {
  query: string;
  algorithm: "semantic" | "hybrid";
  results: KnowledgeCitation[];
}

export const eventTypes: KnownEventType[] = [
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
  "memory.retrieved",
  "memory.retrieval.skipped",
  "memory.written",
  "run.completed",
  "run.failed",
  "run.cancelled",
];
