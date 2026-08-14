import type { RunResult } from "@/lib/api";

export type StudioView = "dashboard" | "agents" | "builder" | "playground" | "run";

export interface RunSnapshot extends RunResult {
  agentName: string;
  latencyMs: number | null;
  toolCalls: number;
}

export interface ToastMessage {
  id: number;
  title: string;
  message: string;
  tone: "success" | "error" | "info";
}
