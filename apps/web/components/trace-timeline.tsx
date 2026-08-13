import type { AgentEvent } from "@/lib/api";

const labels: Record<AgentEvent["type"], string> = {
  "run.started": "Run started",
  "step.started": "Step started",
  "llm.started": "Runtime thinking",
  "llm.retrying": "Retrying invalid output",
  "llm.completed": "Runtime complete",
  "tool.selected": "Tool selected",
  "tool.started": "Tool input",
  "tool.completed": "Tool result",
  "tool.failed": "Tool failed",
  "step.completed": "Step complete",
  "memory.retrieved": "Memory retrieved",
  "memory.written": "Memory written",
  "run.completed": "Final answer",
  "run.failed": "Run failed",
  "run.cancelled": "Run cancelled",
};

function detail(event: AgentEvent): string {
  const payload = event.payload;
  if (typeof payload.result === "string") return payload.result;
  if (payload.result && typeof payload.result === "object") {
    const result = payload.result as Record<string, unknown>;
    if (Array.isArray(result.results)) {
      return `Retrieved ${result.results.length} cited chunk${result.results.length === 1 ? "" : "s"}`;
    }
    return JSON.stringify(payload.result);
  }
  if (typeof payload.final_output === "string") return payload.final_output;
  if (typeof payload.error === "string") return payload.error;
  if (typeof payload.summary === "string") return payload.summary;
  if (typeof payload.tool === "string" && payload.arguments) {
    return `${payload.tool} · ${JSON.stringify(payload.arguments)}`;
  }
  if (typeof payload.tool === "string") return payload.tool;
  return JSON.stringify(payload);
}

function citations(event: AgentEvent): Array<Record<string, unknown>> {
  if (Array.isArray(event.payload.citations)) {
    return event.payload.citations as Array<Record<string, unknown>>;
  }
  const result = event.payload.result;
  if (result && typeof result === "object" && "results" in result) {
    const nested = (result as Record<string, unknown>).results;
    if (Array.isArray(nested)) return nested as Array<Record<string, unknown>>;
  }
  return [];
}

export function TraceTimeline({ events }: { events: AgentEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="empty-trace">
        <span className="pulse-dot" />
        运行后，这里会按顺序显示真实事件。
      </div>
    );
  }
  return (
    <ol className="timeline" aria-label="Run trace events">
      {events.map((event) => {
        const eventCitations = citations(event);
        return (
        <li key={event.event_id} className={event.type.includes("failed") ? "event failed" : "event"}>
          <div className="event-rail">
            <span className="event-dot" />
          </div>
          <div className="event-content">
            <div className="event-heading">
              <strong>{labels[event.type]}</strong>
              <span>#{event.sequence}</span>
            </div>
            <p>{detail(event)}</p>
            {eventCitations.length > 0 && (
              <div className="trace-citations">
                {eventCitations.map((citation, index) => (
                  <details key={String(citation.chunk_id ?? index)}>
                    <summary>
                      [{index + 1}] {String(citation.document ?? "Source")} · score {Number(citation.score ?? 0).toFixed(3)}
                    </summary>
                    <p>{String(citation.content ?? "")}</p>
                    <small>{String(citation.source ?? "")} · chunk #{String(citation.chunk_index ?? "")}</small>
                  </details>
                ))}
              </div>
            )}
            {typeof event.payload.latency_ms === "number" && (
              <small>{event.payload.latency_ms} ms</small>
            )}
          </div>
        </li>
        );
      })}
    </ol>
  );
}
