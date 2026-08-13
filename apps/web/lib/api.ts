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
      headers: {
        ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
    });
  } catch {
    throw new Error("Cannot connect to the Agent Studio API. Confirm that the backend is running on port 8000.");
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `API request failed (${response.status}).`);
  }
  return (await response.json()) as T;
}

export const api = {
  listAgents: () => request<AgentDefinition[]>("/agents"),
  createAgent: (payload: {
    name: string;
    instructions: string;
    runtime_mode: RuntimeMode;
    model: string | null;
    tools: string[];
    knowledge_base_ids?: string[];
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
  "run.completed",
  "run.failed",
  "run.cancelled",
];
