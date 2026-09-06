import { useCallback, useState } from "react";

import { usePoll } from "../hooks/usePoll";

import { api } from "../api/client";
import { ChunkInspector } from "../components/ChunkInspector";
import { DocumentCard, type DocumentActions } from "../components/DocumentCard";
import { ExcludedViewer } from "../components/ExcludedViewer";
import { PageImageViewer } from "../components/PageImageViewer";
import type { Connection } from "../components/Shell";
import { Uploader } from "../components/Uploader";
import { WorkerPanel } from "../components/WorkerPanel";
import { EmptyState, ErrorState, Spinner } from "../components/states";
import type { ApiError, DocumentRecord, WorkerStatus } from "../types/api";

type Load =
  | { state: "loading" }
  | { state: "error"; error: ApiError; disconnected: boolean }
  | { state: "ready"; documents: DocumentRecord[] };

type Drawer =
  | { kind: "none" }
  | { kind: "chunks"; doc: DocumentRecord }
  | { kind: "excluded"; doc: DocumentRecord }
  | { kind: "pages"; doc: DocumentRecord };

/** A document in any of these is finished; the row will not change again. */
const SETTLED = new Set(["ready", "failed", "no_searchable_content"]);

/** What a document held by no discipline is called on screen.
 *
 *  It is a REAL group, not a leftovers bin: no discipline holds these, so only
 *  an administrator can read them. The same words as the badge on the card,
 *  deliberately - two names for one state is how a reader ends up believing
 *  they are two states.
 */
export const UNCATEGORISED_GROUP = "Admin only";

export type DocumentGroup = { name: string; documents: DocumentRecord[] };

/**
 * The documents, grouped by the discipline that holds them.
 *
 * ONE DOCUMENT CAN APPEAR IN MORE THAN ONE GROUP, and that is correct rather
 * than a duplicate: `disciplines` is many-to-many because a grant is, and a
 * document granted to Civil and Mechanical genuinely belongs to both. Showing
 * it once - under whichever discipline happened to sort first - would tell a
 * Mechanical reader it was not theirs.
 *
 * Group order is alphabetical, with `Admin only` pinned last: it is the group
 * a reader is least likely to be looking for, and pinning it stops it moving
 * as disciplines are added. Within a group the API's order is preserved, which
 * is most-recent-upload-first.
 */
export function groupByDiscipline(documents: DocumentRecord[]): DocumentGroup[] {
  const byName = new Map<string, DocumentRecord[]>();
  for (const doc of documents) {
    const names = doc.disciplines.length > 0 ? doc.disciplines : [UNCATEGORISED_GROUP];
    for (const name of names) {
      const bucket = byName.get(name);
      if (bucket) bucket.push(doc);
      else byName.set(name, [doc]);
    }
  }
  return [...byName.entries()]
    .map(([name, docs]) => ({ name, documents: docs }))
    .sort((a, b) => {
      if (a.name === UNCATEGORISED_GROUP) return 1;
      if (b.name === UNCATEGORISED_GROUP) return -1;
      return a.name.localeCompare(b.name);
    });
}

export function DocumentsView({
  connection,
  onRetryConnection,
}: {
  connection: Connection;
  onRetryConnection: () => void;
}) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  // Worker DETAIL from the scoped metrics route, never from health.
  const [worker, setWorker] = useState<WorkerStatus | null>(null);
  const [drawer, setDrawer] = useState<Drawer>({ kind: "none" });
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const m = await api.metrics();
    setWorker(m.ok ? m.data.worker : null);
    const result = await api.documents();
    if (result.ok) {
      setLoad({ state: "ready", documents: result.data });
    } else {
      setLoad({
        state: "error",
        error: result.error,
        disconnected: result.disconnected,
      });
    }
  }, []);

  // Poll so ingestion progress is live without the operator refreshing - but
  // only FAST while there is progress to be live about. On an idle corpus the
  // old fixed 3 s was 20 requests a minute, forever, against a 15 W CPU that
  // is also answering questions.
  //
  // The signal is the list this screen already has: a document that is not
  // settled is still being worked on. That needs no extra request, and it
  // cannot disagree with the rows on screen the way a separate worker flag
  // could. `busy` - an upload or a retry in flight - forces fast immediately
  // so an action does not wait out the idle interval.
  const working =
    busy !== null ||
    (load.state === "ready" && load.documents.some((d) => !SETTLED.has(d.status)));

  usePoll(refresh, working);

  const run = useCallback(
    async (doc: DocumentRecord, label: string, call: () => Promise<{ ok: boolean }>) => {
      setBusy(doc.id);
      setNotice(`${label} ${doc.filename}…`);
      const result = await call();
      setBusy(null);
      setNotice(result.ok ? `${label} finished for ${doc.filename}` : `${label} failed`);
      void refresh();
    },
    [refresh],
  );

  const actions: DocumentActions = {
    busy,
    onInspect: (doc) => setDrawer({ kind: "chunks", doc }),
    onExcluded: (doc) => setDrawer({ kind: "excluded", doc }),
    onPages: (doc) => setDrawer({ kind: "pages", doc }),
    onExtract: (doc) => void run(doc, "Extract", () => api.extract(doc.id)),
    onChunk: (doc) => void run(doc, "Chunk", () => api.chunk(doc.id)),
    onEmbed: (doc) => void run(doc, "Embed", () => api.embed(doc.id)),
    onDelete: (doc) =>
      void run(doc, "Delete", async () => {
        const r = await api.remove(doc.id);
        if (r.ok) setDrawer({ kind: "none" });
        return r;
      }),
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-slateish-200">Documents</h1>
        <p className="mt-1 text-sm text-slateish-400">
          Upload, inspect, and verify what the system can actually search.
        </p>
      </header>

      {/* The worker DETAIL comes from /api/metrics, scoped as of the commit
          that corrected this comment - it previously discarded the scope it
          resolved, so this sentence was a belief rather than a fact. Health
          is unauthenticated and now carries only alive/busy/stalled, so this
          panel names the document being processed only to a reader entitled
          to see it. */}
      <WorkerPanel
        connection={connection}
        documents={load.state === "ready" ? load.documents : []}
        worker={worker}
      />

      <Uploader onUploaded={refresh} />

      {notice && (
        <p role="status" aria-live="polite" className="text-xs text-slateish-400">
          {notice}
        </p>
      )}

      <section aria-labelledby="documents-heading">
        <h2 id="documents-heading" className="sr-only">
          Document list
        </h2>

        {load.state === "loading" && <Spinner label="Loading documents" />}

        {load.state === "error" &&
          (load.disconnected ? (
            // The shell already shows the full disconnected explanation once.
            // Repeating it here would be noise, so this is a short pointer.
            <p className="text-sm text-warn-500">
              Document list unavailable while the backend is unreachable.{" "}
              <button
                type="button"
                onClick={onRetryConnection}
                className="underline decoration-dotted"
              >
                Retry
              </button>
            </p>
          ) : (
            <ErrorState error={load.error} onRetry={refresh} />
          ))}

        {load.state === "ready" && load.documents.length === 0 && (
          <EmptyState
            title="No documents yet"
            hint="Drag a PDF onto the box above to start."
          />
        )}

        {load.state === "ready" && load.documents.length > 0 && (
          <div className="space-y-6">
            {groupByDiscipline(load.documents).map((group) => (
              <div key={group.name}>
                <h3
                  className="mb-2 flex items-baseline gap-2 text-[11px] font-semibold uppercase tracking-wider text-slateish-400"
                  aria-label={`${group.name}, ${group.documents.length} document(s)`}
                >
                  {group.name}
                  <span className="font-mono text-slateish-500">
                    {group.documents.length}
                  </span>
                </h3>
                <ul className="space-y-3">
                  {group.documents.map((doc) => (
                    <DocumentCard key={doc.id} doc={doc} actions={actions} />
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </section>

      {drawer.kind === "chunks" && (
        <ChunkInspector doc={drawer.doc} onClose={() => setDrawer({ kind: "none" })} />
      )}
      {drawer.kind === "excluded" && (
        <ExcludedViewer doc={drawer.doc} onClose={() => setDrawer({ kind: "none" })} />
      )}
      {drawer.kind === "pages" && (
        <PageImageViewer doc={drawer.doc} onClose={() => setDrawer({ kind: "none" })} />
      )}
    </div>
  );
}
