import { Icon, type IconName } from "@/components/icons";
import type { AgentEvent, KnownEventType } from "@/lib/api";

interface EventMeta { label: string; category: string; icon: IconName }

const eventMeta: Record<KnownEventType, EventMeta> = {
  "run.started": { label: "Run started", category: "System", icon: "play" },
  "step.started": { label: "Step started", category: "Runtime", icon: "terminal" },
  "llm.started": { label: "LLM request", category: "Model", icon: "spark" },
  "llm.retrying": { label: "LLM retry", category: "Model", icon: "refresh" },
  "llm.completed": { label: "LLM response", category: "Model", icon: "spark" },
  "tool.selected": { label: "Tool selected", category: "Routing", icon: "tool" },
  "tool.started": { label: "Tool call", category: "Tool", icon: "tool" },
  "tool.completed": { label: "Tool result", category: "Tool", icon: "check" },
  "tool.failed": { label: "Tool failed", category: "Error", icon: "error" },
  "step.completed": { label: "Step completed", category: "Runtime", icon: "check" },
  "run.completed": { label: "Final answer", category: "Output", icon: "check" },
  "run.failed": { label: "Run failed", category: "Error", icon: "error" },
  "run.cancelled": { label: "Run cancelled", category: "System", icon: "close" },
};

function metaFor(event: AgentEvent): EventMeta {
  return eventMeta[event.type as KnownEventType] ?? {
    label: event.type,
    category: "Event",
    icon: "terminal",
  };
}

export function toolMeta(tool: string): { label: string; icon: IconName; tone: string } {
  const normalized = tool.toLowerCase();
  if (normalized.includes("calculator")) return { label: "Calculator", icon: "calculator", tone: "calculator" };
  if (normalized.includes("knowledge") || normalized.includes("search")) return { label: "Knowledge", icon: "knowledge", tone: "knowledge" };
  if (normalized.includes("http") || normalized.includes("request")) return { label: "HTTP", icon: "http", tone: "http" };
  return { label: tool, icon: "tool", tone: "default" };
}

function detail(event: AgentEvent): string {
  const payload = event.payload;
  if (typeof payload.result === "string") return payload.result;
  if (payload.result && typeof payload.result === "object") {
    const result = payload.result as Record<string, unknown>;
    if (Array.isArray(result.results)) {
      return `Retrieved ${result.results.length} cited chunk${result.results.length === 1 ? "" : "s"}`;
    }
    return JSON.stringify(payload.result, null, 2);
  }
  if (typeof payload.final_output === "string") return payload.final_output;
  if (typeof payload.error === "string") return payload.error;
  if (typeof payload.summary === "string") return payload.summary;
  if (payload.arguments && typeof payload.arguments === "object") return JSON.stringify(payload.arguments, null, 2);
  if (typeof payload.reason === "string") return payload.reason;
  if (typeof payload.runtime === "string") return `${payload.runtime} runtime`;
  const serializable = Object.fromEntries(Object.entries(payload).filter(([key]) => key !== "tool" && key !== "latency_ms"));
  return Object.keys(serializable).length ? JSON.stringify(serializable, null, 2) : "Event recorded";
}

function citations(event: AgentEvent): Array<Record<string, unknown>> {
  if (Array.isArray(event.payload.citations)) return event.payload.citations as Array<Record<string, unknown>>;
  const result = event.payload.result;
  if (result && typeof result === "object" && "results" in result) {
    const nested = (result as Record<string, unknown>).results;
    if (Array.isArray(nested)) return nested as Array<Record<string, unknown>>;
  }
  return [];
}

function CitationList({ items }: { items: Array<Record<string, unknown>> }) {
  if (!items.length) return null;
  return (
    <div className="trace-citations" aria-label="Knowledge citations">
      {items.map((citation, index) => (
        <details key={String(citation.chunk_id ?? index)}>
          <summary>
            [{index + 1}] {String(citation.document ?? "Source")} · score {Number(citation.score ?? 0).toFixed(3)}
          </summary>
          <p>{String(citation.content ?? "")}</p>
          <dl>
            <div><dt>Source</dt><dd>{String(citation.source ?? "Unknown")}</dd></div>
            <div><dt>Document</dt><dd>{String(citation.document_id ?? citation.document ?? "Unknown")}</dd></div>
            <div><dt>Chunk</dt><dd>#{String(citation.chunk_index ?? "—")} · {String(citation.chunk_id ?? "Unknown")}</dd></div>
            {typeof citation.metadata === "object" && citation.metadata !== null && (
              <div><dt>Metadata</dt><dd><code>{JSON.stringify(citation.metadata)}</code></dd></div>
            )}
          </dl>
        </details>
      ))}
    </div>
  );
}

export function TraceTimeline({ events }: { events: AgentEvent[] }) {
  if (events.length === 0) {
    return <div className="trace-empty"><span className="trace-empty-visual"><Icon name="terminal" /><i /><i /><i /></span><h3>Trace will appear here</h3><p>Each model step and tool call is streamed in execution order.</p></div>;
  }
  return (
    <ol className="trace-list" aria-label="Live run trace">
      {events.map((event) => {
        const meta = metaFor(event);
        const tool = typeof event.payload.tool === "string" ? toolMeta(event.payload.tool) : null;
        const failed = event.type.includes("failed");
        const eventCitations = citations(event);
        return <li key={event.event_id} className={`trace-event ${failed ? "failed" : ""}`}>
          <div className="trace-rail"><span><Icon name={meta.icon} /></span></div>
          <article>
            <div className="trace-event-heading"><div><small>{meta.category}</small><strong>{meta.label}</strong></div><time dateTime={event.timestamp}>#{event.sequence}</time></div>
            {tool && <span className={`tool-type tool-${tool.tone}`}><Icon name={tool.icon} />{tool.label}</span>}
            <pre>{detail(event)}</pre>
            <CitationList items={eventCitations} />
            {typeof event.payload.latency_ms === "number" && <span className="latency"><Icon name="clock" />{event.payload.latency_ms} ms</span>}
          </article>
        </li>;
      })}
    </ol>
  );
}
