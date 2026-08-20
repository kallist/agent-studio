import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TraceTimeline } from "@/components/trace-timeline";
import type { AgentEvent } from "@/lib/api";

describe("TraceTimeline", () => {
  it("renders the empty trace state", () => {
    render(<TraceTimeline events={[]} />);
    expect(screen.getByRole("heading", { name: "Trace will appear here" })).toBeInTheDocument();
    expect(screen.getByText(/streamed in execution order/i)).toBeInTheDocument();
  });

  it("renders calculator tool details", () => {
    const timestamp = new Date().toISOString();
    const events: AgentEvent[] = [
      { event_id: "one", run_id: "run", sequence: 1, type: "tool.started", timestamp, payload: { tool: "calculator", arguments: { expression: "128 * 37 + 456" } } },
      { event_id: "two", run_id: "run", sequence: 2, type: "tool.completed", timestamp, payload: { tool: "calculator", result: { result: "5192" }, latency_ms: 1.2 } },
      { event_id: "three", run_id: "run", sequence: 3, type: "run.completed", timestamp, payload: { final_output: "5192" } },
    ];
    render(<TraceTimeline events={events} />);
    expect(screen.getByText("Tool call")).toBeInTheDocument();
    expect(screen.getByText("Tool result")).toBeInTheDocument();
    expect(screen.getAllByText("Calculator")).toHaveLength(2);
    expect(screen.getByText("1.2 ms")).toBeInTheDocument();
  });

  it("preserves knowledge citation metadata and tolerates unknown events", () => {
    const timestamp = new Date().toISOString();
    const events: AgentEvent[] = [
      {
        event_id: "knowledge",
        run_id: "run",
        sequence: 1,
        type: "tool.completed",
        timestamp,
        payload: {
          tool: "knowledge_search",
          result: {
            query: "ownership",
            algorithm: "hybrid",
            results: [{ document_id: "doc-1", document: "handbook.md", chunk_id: "chunk-1", chunk_index: 2, source: "upload://handbook.md", score: 0.9123, content: "Knowledge retrieval is application-owned.", metadata: { page: 4 } }],
          },
        },
      },
      { event_id: "future", run_id: "run", sequence: 2, type: "policy.checked", timestamp, payload: { policy: "safe" } },
    ];
    render(<TraceTimeline events={events} />);
    expect(screen.getByText("Knowledge")).toBeInTheDocument();
    expect(screen.getByText(/handbook\.md · score 0\.912/)).toBeInTheDocument();
    expect(screen.getByText("policy.checked")).toBeInTheDocument();
    expect(screen.getByText(/upload:\/\/handbook\.md/)).toBeInTheDocument();
    expect(screen.getByText(/page.*4/)).toBeInTheDocument();
  });

  it("renders normalized durable memory events", () => {
    const timestamp = new Date().toISOString();
    render(<TraceTimeline events={[
      { event_id: "retrieve", run_id: "run", sequence: 1, type: "memory.retrieved", timestamp, payload: { count: 1, matches: [{ memory_id: "memory-1", score: 0.88 }] } },
      { event_id: "write", run_id: "run", sequence: 2, type: "memory.written", timestamp, payload: { memory_id: "memory-2", importance: 0.9 } },
    ]} />);
    expect(screen.getByText("Memory retrieved")).toBeInTheDocument();
    expect(screen.getByText("Memory written")).toBeInTheDocument();
    expect(screen.getAllByText("Memory")).toHaveLength(3);
  });

  it("filters tools without losing unknown events from All", async () => {
    const timestamp = new Date().toISOString();
    render(<TraceTimeline events={[
      { event_id: "tool", run_id: "run", sequence: 1, type: "tool.started", timestamp, payload: { tool: "calculator", arguments: { expression: "1 + 1" } } },
      { event_id: "memory", run_id: "run", sequence: 2, type: "memory.retrieved", timestamp, payload: { count: 1 } },
      { event_id: "future", run_id: "run", sequence: 3, type: "policy.checked", timestamp, payload: { policy: "safe" } },
    ]} />);

    fireEvent.click(screen.getByRole("button", { name: "Tools" }));
    expect(screen.getByText("Calculator")).toBeInTheDocument();
    expect(screen.queryByText("Memory retrieved")).not.toBeInTheDocument();
    expect(screen.queryByText("policy.checked")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByText("Memory retrieved")).toBeInTheDocument();
    expect(screen.getByText("policy.checked")).toBeInTheDocument();
  });

  it("renders redacted structured payloads without restoring secrets", () => {
    const timestamp = new Date().toISOString();
    render(<TraceTimeline events={[
      { event_id: "redacted", run_id: "run", sequence: 1, type: "tool.started", timestamp, payload: { tool: "fixture", arguments: { api_key: "[REDACTED]" } } },
    ]} />);
    expect(screen.getByText(/\[REDACTED\]/)).toBeInTheDocument();
    expect(screen.queryByText(/secret-key/)).not.toBeInTheDocument();
  });
});
