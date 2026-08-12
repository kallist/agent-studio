import type { AgentEvent } from "@/lib/api";

const labels: Record<AgentEvent["type"], string> = {
  "run.started": "Run started",
  "llm.started": "Runtime thinking",
  "llm.completed": "Runtime complete",
  "tool.selected": "Tool selected",
  "tool.started": "Tool input",
  "tool.completed": "Tool result",
  "tool.failed": "Tool failed",
  "run.completed": "Final answer",
  "run.failed": "Run failed",
};

function detail(event: AgentEvent): string {
  const payload = event.payload;
  if (typeof payload.result === "string") return payload.result;
  if (typeof payload.final_output === "string") return payload.final_output;
  if (typeof payload.error === "string") return payload.error;
  if (typeof payload.summary === "string") return payload.summary;
  if (typeof payload.tool === "string" && payload.arguments) {
    return `${payload.tool} · ${JSON.stringify(payload.arguments)}`;
  }
  if (typeof payload.tool === "string") return payload.tool;
  return JSON.stringify(payload);
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
      {events.map((event) => (
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
            {typeof event.payload.latency_ms === "number" && (
              <small>{event.payload.latency_ms} ms</small>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
