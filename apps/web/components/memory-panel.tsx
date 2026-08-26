import type { MemoryRecord } from "@/lib/api";
import { useI18n } from "@/i18n/provider";

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
  const { formatDate, t } = useI18n();
  return (
    <section className="memory-section" aria-labelledby="memory-heading">
      <div className="memory-heading-row">
        <div>
          <p className="eyebrow">{t("memory.eyebrow")}</p>
          <h3 id="memory-heading">{t("memory.title")}</h3>
        </div>
        <label className="memory-toggle">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => onToggle(event.target.checked)}
            disabled={updating}
          />
          <span>{updating ? t("memory.updating") : enabled ? t("memory.on") : t("memory.off")}</span>
        </label>
      </div>
      {!enabled && (
        <p className="memory-note">{t("memory.disabledNote")}</p>
      )}
      {error ? (
        <p className="memory-note memory-error" role="alert">{error}</p>
      ) : loading ? (
        <div className="memory-skeleton" aria-label={t("common.loading.memory")}><span /><span /></div>
      ) : memories.length === 0 ? (
        <p className="memory-note">{t("memory.empty")}</p>
      ) : (
        <ul className="memory-list">
          {memories.map((memory) => (
            <li key={memory.id}>
              <div>
                <p>{memory.content}</p>
                <small>
                  {t("memory.factMeta", { importance: memory.importance.toFixed(1), expires: memory.expires_at ? formatDate(memory.expires_at, { dateStyle: "medium" }) : t("common.values.never") })}
                </small>
              </div>
              <button
                type="button"
                className="memory-delete"
                onClick={() => onDelete(memory.id)}
                disabled={updating}
                aria-label={t("memory.deleteAria", { content: memory.content })}
              >
                {t("common.actions.delete")}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
