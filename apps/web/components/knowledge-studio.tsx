"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  api,
  KnowledgeBase,
  KnowledgeCitation,
  KnowledgeDocument,
} from "@/lib/api";
import { displayStatus } from "@/i18n/display";
import { useI18n } from "@/i18n/provider";

interface KnowledgeStudioProps {
  bases: KnowledgeBase[];
  onBasesChange: (bases: KnowledgeBase[]) => void;
}

export function KnowledgeStudio({ bases, onBasesChange }: KnowledgeStudioProps) {
  const { t } = useI18n();
  const [selectedId, setSelectedId] = useState<string | null>(bases[0]?.id ?? null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [results, setResults] = useState<KnowledgeCitation[]>([]);
  const [busy, setBusy] = useState(false);
  const [documentsLoading, setDocumentsLoading] = useState(Boolean(bases[0]?.id));
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const effectiveSelectedId = selectedId ?? bases[0]?.id ?? null;
  const selected = useMemo(
    () => bases.find((base) => base.id === effectiveSelectedId) ?? null,
    [bases, effectiveSelectedId],
  );

  const refreshDocuments = useCallback(async (baseId: string) => {
    const loaded = await api.listDocuments(baseId);
    setDocuments(loaded);
    return loaded;
  }, []);

  useEffect(() => {
    if (!effectiveSelectedId) return;
    let active = true;
    void api.listDocuments(effectiveSelectedId).then(
      (loaded) => { if (active) setDocuments(loaded); },
      (reason: unknown) => {
        if (active) {
          setError(reason instanceof Error ? reason.message : t("knowledge.loadFailed"));
        }
      },
    ).finally(() => { if (active) setDocumentsLoading(false); });
    return () => { active = false; };
  }, [effectiveSelectedId, t]);

  async function createBase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const created = await api.createKnowledgeBase(
        String(data.get("name")),
        String(data.get("description")),
      );
      onBasesChange([created, ...bases]);
      setSelectedId(created.id);
      setDocuments([]);
      setResults([]);
      setDocumentsLoading(true);
      form.reset();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("knowledge.createFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const input = event.currentTarget.elements.namedItem("file") as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const accepted = await api.uploadDocument(selected.id, file);
      await refreshDocuments(selected.id);
      await pollJob(selected.id, accepted.ingestion_job.id);
      input.value = "";
      const updated = await api.listKnowledgeBases();
      onBasesChange(updated);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("knowledge.uploadFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function pollJob(baseId: string, jobId: string) {
    for (let attempt = 0; attempt < 100; attempt += 1) {
      const job = await api.getIngestionJob(jobId);
      await refreshDocuments(baseId);
      if (job.state === "completed") return;
      if (job.state === "failed") throw new Error(job.error ?? t("knowledge.ingestionFailed"));
      await new Promise((resolve) => window.setTimeout(resolve, 100));
    }
    throw new Error(t("knowledge.ingestionRunning"));
  }

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true);
    setError(null);
    setSearched(true);
    const data = new FormData(event.currentTarget);
    try {
      const response = await api.searchKnowledge(selected.id, String(data.get("query")));
      setResults(response.results);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("knowledge.searchFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="knowledge-section" aria-labelledby="knowledge-heading" aria-busy={busy}>
      <div className="knowledge-heading">
        <div>
          <p className="eyebrow">{t("knowledge.eyebrow")}</p>
          <h2 id="knowledge-heading">{t("knowledge.title")}</h2>
          <p>{t("knowledge.description")}</p>
        </div>
        <form className="compact-form" onSubmit={createBase}>
          <label>
            {t("knowledge.baseName")}
            <input name="name" placeholder={t("knowledge.basePlaceholder")} required maxLength={120} />
          </label>
          <label>
            {t("knowledge.descriptionLabel")}
            <input name="description" placeholder={t("knowledge.descriptionPlaceholder")} maxLength={2000} />
          </label>
          <button className="primary-button" disabled={busy}>{busy ? t("knowledge.working") : t("common.actions.create")}</button>
        </form>
      </div>

      {error && <div className="knowledge-error" role="alert">{error}</div>}
      <div className="knowledge-grid">
        <div className="knowledge-collections">
          <h3>{t("knowledge.collections")} <span>{bases.length}</span></h3>
          {bases.length === 0 ? (
            <p className="muted-copy">{t("knowledge.emptyCollections")}</p>
          ) : (
            bases.map((base) => (
              <button
                key={base.id}
                className={base.id === effectiveSelectedId ? "collection-card selected" : "collection-card"}
                onClick={() => { setSelectedId(base.id); setDocuments([]); setDocumentsLoading(true); setError(null); setResults([]); setSearched(false); }}
              >
                <strong>{base.name}</strong>
                <small>{t(base.document_count === 1 ? "common.counts.documentsOne" : "common.counts.documentsOther", { count: base.document_count })} · {base.embedding_provider}/{base.embedding_model} · {base.embedding_dimensions}d</small>
              </button>
            ))
          )}
        </div>

        <div className="knowledge-documents">
          <div className="knowledge-panel-title">
            <div><h3>{selected?.name ?? t("knowledge.documents")}</h3><p>{selected?.description}</p></div>
            {selected && (
              <form onSubmit={upload} className="upload-form">
                <label className="file-button">
                  <span>{t("knowledge.chooseFile")}</span>
                  <input name="file" type="file" accept=".txt,.md,.pdf,text/plain,text/markdown,application/pdf" required />
                </label>
                <button disabled={busy}>{t("knowledge.uploadIngest")}</button>
              </form>
            )}
          </div>
          <div className="document-list" aria-live="polite">
            {documentsLoading && <div className="knowledge-skeleton" aria-label={t("common.loading.documents")}><span /><span /></div>}
            {documents.map((document) => (
              <article key={document.id} className="document-row">
                <div><strong>{document.filename}</strong><small>{formatBytes(document.size_bytes)} · {document.mime_type}</small></div>
                <span className={`ingestion-state ${document.ingestion?.state ?? "queued"}`}>
                  {displayStatus(t, document.ingestion?.state ?? "queued")}
                </span>
                {document.ingestion?.error && <p>{document.ingestion.error}</p>}
              </article>
            ))}
            {selected && !documentsLoading && documents.length === 0 && <p className="muted-copy">{t("knowledge.noDocuments")}</p>}
          </div>
        </div>

        <div className="knowledge-search">
          <form onSubmit={search}>
            <label htmlFor="knowledge-query">{t("knowledge.testRetrieval")}</label>
            <textarea id="knowledge-query" name="query" rows={3} required placeholder={t("knowledge.queryPlaceholder")} />
            <button className="primary-button" disabled={busy || !selected}>{busy ? t("knowledge.searching") : t("knowledge.hybridSearch")}</button>
          </form>
          <div className="retrieval-results" aria-live="polite">
            {results.map((result, index) => (
              <details key={result.chunk_id} className="source-card" open={index === 0}>
                <summary>
                  <span>[{index + 1}] {result.document}</span>
                  <strong>{t("knowledge.score")} {result.score.toFixed(3)}</strong>
                </summary>
                <p>{result.content}</p>
                <dl>
                  <div><dt>{t("knowledge.source")}</dt><dd>{result.source}</dd></div>
                  <div><dt>{t("knowledge.chunk")}</dt><dd>#{result.chunk_index} · {result.chunk_id}</dd></div>
                  {typeof result.metadata.page === "number" && <div><dt>{t("knowledge.page")}</dt><dd>{result.metadata.page}</dd></div>}
                </dl>
              </details>
            ))}
            {searched && !busy && results.length === 0 && <p className="muted-copy">{t("knowledge.noMatches")}</p>}
          </div>
        </div>
      </div>
    </section>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}
