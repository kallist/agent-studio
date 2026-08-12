import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TraceTimeline } from "@/components/trace-timeline";
import type { AgentEvent } from "@/lib/api";

describe("TraceTimeline", () => {
  it("renders the empty state", () => {
    render(<TraceTimeline events={[]} />);
    expect(screen.getByText(/运行后/)).toBeInTheDocument();
  });

  it("renders ordered tool and final output details", () => {
    const events: AgentEvent[] = [
      {
        event_id: "one",
        run_id: "run",
        sequence: 1,
        type: "tool.completed",
        timestamp: new Date().toISOString(),
        payload: { tool: "calculator", result: "5192", latency_ms: 1.2 },
      },
      {
        event_id: "two",
        run_id: "run",
        sequence: 2,
        type: "run.completed",
        timestamp: new Date().toISOString(),
        payload: { final_output: "5192" },
      },
    ];
    render(<TraceTimeline events={events} />);
    expect(screen.getByText("Tool result")).toBeInTheDocument();
    expect(screen.getByText("Final answer")).toBeInTheDocument();
    expect(screen.getAllByText("5192")).toHaveLength(2);
  });
});
