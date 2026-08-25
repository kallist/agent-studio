"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  api,
  KnowledgeBase,
  KnowledgeCitation,
  KnowledgeDocument,
} from "@/lib/api";

interface KnowledgeStudioProps {
  bases: KnowledgeBase[];
  onBasesChange: (bases: KnowledgeBase[]) => void;
}

export function KnowledgeStudio({ bases, onBasesChange }: KnowledgeStudioProps) {
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
          setError(reason instanceof Error ? reason.message : "Unable to load documents.");
        }
      },
    ).finally(() => { if (active) setDocumentsLoading(false); });
    return () => { active = false; };
  }, [effectiveSelectedId]);

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
      setError(reason instanceof Error ? reason.message : "Unable to create knowledge base.");
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
      setError(reason instanceof Error ? reason.message : "Unable to upload document.");
    } finally {
      setBusy(false);
    }
  }

  async function pollJob(baseId: string, jobId: string) {
    for (let attempt = 0; attempt < 100; attempt += 1) {
      const job = await api.getIngestionJob(jobId);
      await refreshDocuments(baseId);
      if (job.state === "completed") return;
      if (job.state === "failed") throw new Error(job.error ?? "Ingestion failed.");
      await new Promise((resolve) => window.setTimeout(resolve, 100));
    }
    throw new Error("Ingestion is still running. Refresh to check its status.");
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
      setError(reason instanceof Error ? reason.message : "Search failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="knowledge-section" aria-labelledby="knowledge-heading" aria-busy={busy}>
      <div className="knowledge-heading">
        <div>
          <p className="eyebrow">KNOWLEDGE / RAG</p>
          <h2 id="knowledge-heading">Ground agents in inspectable sources.</h2>
          <p>Create a collection, ingest real documents asynchronously, and inspect ranked chunks.</p>
        </div>
        <form className="compact-form" onSubmit={createBase}>
          <label>
            Knowledge base name
            <input name="name" placeholder="Product handbook" required maxLength={120} />
          </label>
          <label>
            Description
            <input name="description" placeholder="Policies and operating notes" maxLength={2000} />
          </label>
          <button className="primary-button" disabled={busy}>{busy ? "Working…" : "Create"}</button>
        </form>
      </div>

      {error && <div className="knowledge-error" role="alert">{error}</div>}
      <div className="knowledge-grid">
        <div className="knowledge-collections">
          <h3>Collections <span>{bases.length}</span></h3>
          {bases.length === 0 ? (
            <p className="muted-copy">Create a knowledge base to begin.</p>
          ) : (
            bases.map((base) => (
              <button
                key={base.id}
                className={base.id === effectiveSelectedId ? "collection-card selected" : "collection-card"}
                onClick={() => { setSelectedId(base.id); setDocuments([]); setDocumentsLoading(true); setError(null); setResults([]); setSearched(false); }}
              >
                <strong>{base.name}</strong>
                <small>{base.document_count} documents · {base.embedding_provider}/{base.embedding_model} · {base.embedding_dimensions}d</small>
              </button>
            ))
          )}
        </div>

        <div className="knowledge-documents">
          <div className="knowledge-panel-title">
            <div><h3>{selected?.name ?? "Documents"}</h3><p>{selected?.description}</p></div>
            {selected && (
              <form onSubmit={upload} className="upload-form">
                <label className="file-button">
                  <span>Choose txt, md, or pdf</span>
                  <input name="file" type="file" accept=".txt,.md,.pdf,text/plain,text/markdown,application/pdf" required />
                </label>
                <button disabled={busy}>Upload & ingest</button>
              </form>
            )}
          </div>
          <div className="document-list" aria-live="polite">
            {documentsLoading && <div className="knowledge-skeleton" aria-label="Loading documents"><span /><span /></div>}
            {documents.map((document) => (
              <article key={document.id} className="document-row">
                <div><strong>{document.filename}</strong><small>{formatBytes(document.size_bytes)} · {document.mime_type}</small></div>
                <span className={`ingestion-state ${document.ingestion?.state ?? "queued"}`}>
                  {document.ingestion?.state ?? "queued"}
                </span>
                {document.ingestion?.error && <p>{document.ingestion.error}</p>}
              </article>
            ))}
            {selected && !documentsLoading && documents.length === 0 && <p className="muted-copy">No documents uploaded yet.</p>}
          </div>
        </div>

        <div className="knowledge-search">
          <form onSubmit={search}>
            <label htmlFor="knowledge-query">Test retrieval</label>
            <textarea id="knowledge-query" name="query" rows={3} required placeholder="Ask a question about these sources" />
            <button className="primary-button" disabled={busy || !selected}>{busy ? "Searching…" : "Semantic + keyword search"}</button>
          </form>
          <div className="retrieval-results" aria-live="polite">
            {results.map((result, index) => (
              <details key={result.chunk_id} className="source-card" open={index === 0}>
                <summary>
                  <span>[{index + 1}] {result.document}</span>
                  <strong>score {result.score.toFixed(3)}</strong>
                </summary>
                <p>{result.content}</p>
                <dl>
                  <div><dt>Source</dt><dd>{result.source}</dd></div>
                  <div><dt>Chunk</dt><dd>#{result.chunk_index} · {result.chunk_id}</dd></div>
                  {typeof result.metadata.page === "number" && <div><dt>Page</dt><dd>{result.metadata.page}</dd></div>}
                </dl>
              </details>
            ))}
            {searched && !busy && results.length === 0 && <p className="muted-copy">No matching chunks were found.</p>}
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
