import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MemoryPanel } from "@/components/memory-panel";

describe("MemoryPanel", () => {
  it("shows saved facts and exposes delete and disable controls", () => {
    const onDelete = vi.fn();
    const onToggle = vi.fn();
    render(
      <MemoryPanel
        enabled
        loading={false}
        memories={[
          {
            id: "memory-1",
            agent_id: "agent-1",
            kind: "long_term",
            content: "project codename is Atlas",
            importance: 0.9,
            source_run_id: "run-1",
            created_at: "2026-08-13T00:00:00Z",
            expires_at: "2027-02-09T00:00:00Z",
            metadata: { write_reason: "explicit_remember" },
          },
        ]}
        onDelete={onDelete}
        onToggle={onToggle}
      />,
    );

    expect(screen.getByText("project codename is Atlas")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /delete memory/i }));
    expect(onDelete).toHaveBeenCalledWith("memory-1");
    fireEvent.click(screen.getByRole("checkbox"));
    expect(onToggle).toHaveBeenCalledWith(false);
  });
});
