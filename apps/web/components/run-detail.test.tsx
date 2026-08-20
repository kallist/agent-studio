import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RunDetail } from "@/components/run-detail";
import type { AgentEvent, RunObservability, RunResult } from "@/lib/api";

const timestamp = "2026-08-20T00:00:00Z";

function run(status: RunResult["status"] = "completed"): RunResult {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    agent_id: "22222222-2222-2222-2222-222222222222",
    status,
    input: "Calculate 128 * 37 + 456",
    output: status === "completed" ? "5192" : null,
    error: status === "failed" ? "Division by zero is not allowed." : status === "cancelled" ? "Agent run was cancelled by the user." : null,
    created_at: timestamp,
    updated_at: "2026-08-20T00:00:00.125Z",
  };
}

function metrics(status: RunResult["status"] = "completed"): RunObservability {
  return {
    run_id: "11111111-1111-1111-1111-111111111111",
    agent_id: "22222222-2222-2222-2222-222222222222",
    runtime_type: "mock",
    provider_type: "mock",
    status,
    termination_reason: status,
    created_at: timestamp,
    started_at: timestamp,
    terminal_at: "2026-08-20T00:00:00.125Z",
    duration_ms: 125,
    event_count: 4,
    step_count: 2,
    tool_calls: { total: 1, succeeded: status === "completed" ? 1 : 0, failed: status === "failed" ? 1 : 0 },
    usage: { input_tokens: null, output_tokens: null, total_tokens: null },
    error_category: status === "failed" ? "tool_error" : status === "cancelled" ? "cancelled" : null,
    error_summary: status === "failed" ? "Division by zero is not allowed." : status === "cancelled" ? "Agent run was cancelled by the user." : null,
    event_statistics: {},
    tools: [],
  };
}

const events: AgentEvent[] = [
  { event_id: "tool", run_id: "run", sequence: 1, type: "tool.started", timestamp, step_index: 1, tool_call_id: "33333333-3333-3333-3333-333333333333", duration_ms: null, usage: null, payload: { tool: "calculator", arguments: { expression: "128 * 37 + 456" } } },
  { event_id: "done", run_id: "run", sequence: 2, type: "tool.completed", timestamp, step_index: 1, tool_call_id: "33333333-3333-3333-3333-333333333333", duration_ms: 2.5, usage: null, payload: { tool: "calculator", result: { result: "5192" } } },
  { event_id: "memory", run_id: "run", sequence: 3, type: "memory.retrieval.skipped", timestamp, duration_ms: null, usage: null, payload: { count: 0, reason: "no_match_or_threshold" } },
];

describe("RunDetail observability", () => {
  it("renders real summary metrics, token N/A, correlation, and filters", () => {
    render(<RunDetail run={run()} events={events} observability={metrics()} agent={null} onBack={vi.fn()} onRerun={vi.fn()} />);
    expect(screen.getByLabelText("Observability metrics")).toHaveTextContent("125 ms");
    expect(screen.getByLabelText("Observability metrics")).toHaveTextContent("Token UsageN/A");
    expect(screen.getByLabelText("Observability metrics")).toHaveTextContent("Tool Calls1");
    expect(screen.getAllByText("33333333-3333-3333-3333-333333333333")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Tools" }));
    expect(screen.getByRole("heading", { name: "Tool Call" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Memory Retrieval Skipped" })).not.toBeInTheDocument();
  });

  it.each(["failed", "cancelled"] as const)("renders the %s terminal state without success", (status) => {
    render(<RunDetail run={run(status)} events={[]} observability={metrics(status)} agent={null} onBack={vi.fn()} onRerun={vi.fn()} />);
    expect(screen.getAllByText(status, { exact: true }).length).toBeGreaterThan(0);
    expect(screen.queryByText("5192")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Error" })).toBeInTheDocument();
  });
});
