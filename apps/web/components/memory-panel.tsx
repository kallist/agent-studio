import type { MemoryRecord } from "@/lib/api";

interface MemoryPanelProps {
  enabled: boolean;
  loading: boolean;
  updating: boolean;
  error: string | null;
  memories: MemoryRecord[];
  onDelete: (memoryId: string) => void;
  onToggle: (enabled: boolean) => void;
}

export function MemoryPanel({
  enabled,
  loading,
  updating,
  error,
  memories,
  onDelete,
  onToggle,
}: MemoryPanelProps) {
  return (
    <section className="memory-section" aria-labelledby="memory-heading">
      <div className="memory-heading-row">
        <div>
          <p className="eyebrow">LONG-TERM MEMORY</p>
          <h3 id="memory-heading">Remembered facts</h3>
        </div>
        <label className="memory-toggle">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => onToggle(event.target.checked)}
            disabled={updating}
          />
          <span>{updating ? "Updating…" : enabled ? "On" : "Off"}</span>
        </label>
      </div>
      {!enabled && (
        <p className="memory-note">Memory is off. Runs will not retrieve or write facts.</p>
      )}
      {error ? (
        <p className="memory-note memory-error" role="alert">{error}</p>
      ) : loading ? (
        <div className="memory-skeleton" aria-label="Loading durable memory"><span /><span /></div>
      ) : memories.length === 0 ? (
        <p className="memory-note">No durable facts saved for this agent.</p>
      ) : (
        <ul className="memory-list">
          {memories.map((memory) => (
            <li key={memory.id}>
              <div>
                <p>{memory.content}</p>
                <small>
                  Importance {memory.importance.toFixed(1)} · expires {formatDate(memory.expires_at)}
                </small>
              </div>
              <button
                type="button"
                className="memory-delete"
                onClick={() => onDelete(memory.id)}
                disabled={updating}
                aria-label={`Delete memory: ${memory.content}`}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function formatDate(value: string | null): string {
  if (!value) return "never";
  return new Intl.DateTimeFormat("en", { dateStyle: "medium" }).format(new Date(value));
}
