import type { RunObservability } from "@/lib/api";

export type StudioView = "dashboard" | "agents" | "builder" | "playground" | "evaluations" | "run";

export interface RunSnapshot extends RunObservability {
  agentName: string;
}

export interface ToastMessage {
  id: number;
  title: string;
  message: string;
  tone: "success" | "error" | "info";
}
