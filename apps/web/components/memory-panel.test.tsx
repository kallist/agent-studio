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
        updating={false}
        error={null}
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

  it("renders loading, error, and mutation-disabled states", () => {
    const view = render(<MemoryPanel enabled loading updating={false} error={null} memories={[]} onDelete={vi.fn()} onToggle={vi.fn()} />);
    expect(view.getByLabelText("Loading durable memory")).toBeInTheDocument();
    view.rerender(<MemoryPanel enabled loading={false} updating error="Memory API unavailable" memories={[]} onDelete={vi.fn()} onToggle={vi.fn()} />);
    expect(view.getByRole("alert")).toHaveTextContent("Memory API unavailable");
    expect(view.container.querySelector('input[type="checkbox"]')).toBeDisabled();
  });

  it("renders malicious Memory and API error text without creating executable nodes", () => {
    const malicious = '<img src=x onerror="window.__xss=true">';
    const view = render(<MemoryPanel enabled loading={false} updating={false} error={malicious} memories={[{
      id: "memory-xss",
      agent_id: "agent-1",
      kind: "long_term",
      content: malicious,
      importance: 0.9,
      source_run_id: null,
      created_at: "2026-08-13T00:00:00Z",
      expires_at: null,
      metadata: {},
    }]} onDelete={vi.fn()} onToggle={vi.fn()} />);

    expect(screen.getByText(malicious, { exact: true })).toBeInTheDocument();
    expect(view.container.querySelector("img")).toBeNull();
    expect((window as typeof window & { __xss?: boolean }).__xss).not.toBe(true);

    view.rerender(<MemoryPanel enabled loading={false} updating={false} error={malicious} memories={[]} onDelete={vi.fn()} onToggle={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent(malicious);
    expect(view.container.querySelector("img")).toBeNull();
  });
});
