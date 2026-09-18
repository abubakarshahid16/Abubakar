import { useCallback, useState, useRef } from "react";

import { usePoll } from "../hooks/usePoll";

import { api, classification } from "../api/client";
import { ChunkInspector } from "../components/ChunkInspector";
import { DocumentCard, type DocumentActions } from "../components/DocumentCard";
import { ExcludedViewer } from "../components/ExcludedViewer";
import { PageImageViewer } from "../components/PageImageViewer";
import type { Connection } from "../components/Shell";
import { Uploader } from "../components/Uploader";
import { WorkerPanel } from "../components/WorkerPanel";
import { useDocumentClassifications } from "../components/classification/useDocumentClassifications";
import { useTypeVocabularyLoad } from "../components/classification/TypeFilter";
import { EmptyState, ErrorState, Spinner } from "../components/states";
import type { ApiError, DocumentClassification, DocumentRecord, WorkerStatus } from "../types/api";

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
 *
 *  This screen no longer GROUPS by discipline - see `groupByType` below,
 *  which is what the render uses now - but `groupByDiscipline` stays exported
 *  because it is still exercised on its own in
 *  `DocumentsView.grouping.test.tsx`, a file outside this change's ownership.
 *  Removing it would break that file's build for no behavioural gain: the
 *  discipline axis itself is unchanged, only which axis this screen groups
 *  the list by. */
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

/** The filter-chip and group key for "no confirmed type yet". Never a
 *  register type name - the register's own strings come from
 *  `vocabulary.types` and this must never collide with one of them. */
const AWAITING_TYPE = "__awaiting_type__";

/** The heading and filter-chip label for the group above. Kept as one
 *  constant so the filter chip, the group heading and any message about it
 *  are always the same words. */
export const AWAITING_TYPE_LABEL = "Awaiting a type";

export type TypeGroup = { name: string; documents: DocumentRecord[] };

/**
 * A document's confirmed-or-not type, from the per-document classification
 * fetch - NEVER from anything on `DocumentRecord` itself, because
 * `GET /api/documents` does not carry it.
 *
 * A classification that has not answered yet (still in flight) is treated
 * the same as `doc_type: null` for grouping purposes: it renders in the
 * "awaiting a type" group until its real answer arrives, rather than being
 * hidden from the list altogether while loading.
 */
function typeOf(doc: DocumentRecord, byId: Record<string, DocumentClassification>): string | null {
  return byId[doc.id]?.doc_type ?? null;
}

/**
 * The documents, grouped by confirmed-or-guessed type - in the register's
 * own order, one group per `types` entry, plus a final "awaiting a type"
 * group. A type is never invented here: `types` comes from
 * `useTypeVocabulary`, which reads it from the register.
 *
 * Every group is built even when it has no documents - see the empty-group
 * message in the view. Hiding an empty group would be indistinguishable from
 * a group nobody thought to build, and this screen exists to be able to tell
 * the two apart.
 */
export function groupByType(
  documents: DocumentRecord[],
  types: string[],
  byId: Record<string, DocumentClassification>,
): { groups: TypeGroup[]; awaiting: TypeGroup } {
  const groups: TypeGroup[] = types.map((t) => ({ name: t, documents: [] }));
  const byName = new Map(groups.map((g) => [g.name, g]));
  const awaiting: DocumentRecord[] = [];
  for (const doc of documents) {
    const t = typeOf(doc, byId);
    const bucket = t !== null ? byName.get(t) : undefined;
    // A type the classification carries but the register no longer lists is
    // not something this screen invents a group for - the document still
    // has to appear somewhere, so it falls back to "awaiting a type" rather
    // than being silently dropped.
    if (bucket) bucket.documents.push(doc);
    else awaiting.push(doc);
  }
  return { groups, awaiting: { name: AWAITING_TYPE_LABEL, documents: awaiting } };
}

export function DocumentsView({
  connection,
  onRetryConnection,
  isAdmin = false,
  polling = true,
}: {
  connection: Connection;
  onRetryConnection: () => void;
  /** Whether the confirm control may render at all. Defaults to "not admin",
   *  the safe default: `classification.confirm` 404s anyone else, so a
   *  caller this prop has not been taught about must never see the button.
   *  Comes from `hasAdminCapability(auth)` in `Shell.tsx`. */
  isAdmin?: boolean;
  /** Tests and static previews may request one initial read without intervals. */
  polling?: boolean;
}) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  // Worker DETAIL from the scoped metrics route, never from health.
  const [worker, setWorker] = useState<WorkerStatus | null>(null);
  const [drawer, setDrawer] = useState<Drawer>({ kind: "none" });
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedTypes, setSelectedTypes] = useState<string[]>([]);
  const [listQuery, setListQuery] = useState("");
  const [sort, setSort] = useState("uploaded_at");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [totalMatching, setTotalMatching] = useState<number | null>(null);

  const { vocabulary, settled: vocabularySettled } = useTypeVocabularyLoad();

  const refresh = useCallback(async () => {
    // These reads are independent. Start both before yielding so a slow
    // metrics snapshot never delays the document list (and teardown cannot
    // leave a later document request behind after the view is gone).
    const [m, result] = await Promise.all([api.metrics(), api.documents({ limit: 100, q: listQuery, sort, direction })]);
    setWorker(m.ok ? m.data.worker : null);
    if (result.ok) {
      setLoad({ state: "ready", documents: result.data });
      setTotalMatching(Number(result.response?.headers?.get?.("X-Total-Count") ?? result.data.length));
    } else {
      setLoad({
        state: "error",
        error: result.error,
        disconnected: result.disconnected,
      });
    }
  }, [direction, listQuery, sort]);

  const loadMore = useCallback(async () => {
    if (load.state !== "ready") return;
    const result = await api.documents({ limit: 100, offset: load.documents.length, q: listQuery, sort, direction });
    if (result.ok) {
      setLoad({ state: "ready", documents: [...load.documents, ...result.data] });
      setTotalMatching(Number(result.response?.headers?.get?.("X-Total-Count") ?? load.documents.length + result.data.length));
    }
  }, [direction, listQuery, load, sort]);

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

  usePoll(refresh, working, polling);

  const documentIds = load.state === "ready" ? load.documents.map((d) => d.id) : [];
  const {
    byId: classifications,
    setOne: setOneClassification,
    settled: classificationsSettled,
  } =
    useDocumentClassifications(documentIds);
  const classificationsReady = vocabularySettled && classificationsSettled;
  // READ THROUGH A REF in `confirmType`. Depending on `classifications`
  // directly would rebuild the callback on every confirm - the same reason the
  // hook keeps its own ref - and a stale closure here would carry forward a
  // classification from before the last edit.
  const classificationsRef = useRef(classifications);
  classificationsRef.current = classifications;

  const toggleType = useCallback((type: string) => {
    setSelectedTypes((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type],
    );
  }, []);
  const clearTypes = useCallback(() => setSelectedTypes([]), []);

  const confirmType = useCallback(
    async (doc: DocumentRecord, docType: string) => {
      // THE ROUTE IS A FULL REPLACE, NOT A PATCH. `classification_mod.confirm`
      // writes all four fields, so any field this call omits is written NULL
      // and an empty `subject_ids` DELETES the document_subjects rows. Sending
      // `{doc_type}` alone therefore destroyed the discipline, the class and
      // every subject the register had matched - on a routine Confirm click,
      // and the card reported success. Every field is now carried forward
      // explicitly; only `doc_type` changes.
      const current = classificationsRef.current[doc.id];
      if (!current) {
        // REFUSE RATHER THAN GUESS. Without the current row there is nothing
        // to carry forward, and writing nulls would be the same data loss by
        // another route. A classification we cannot preserve is one we must
        // not overwrite.
        setNotice(
          `Cannot confirm ${doc.filename} yet - its current classification has not loaded. Try again in a moment.`,
        );
        return;
      }
      const result = await classification.confirm(doc.id, {
        doc_type: docType,
        discipline: current.discipline,
        doc_class: current.doc_class,
        subject_ids: current.subjects.map((subject) => subject.id),
      });
      if (result.ok) {
        setOneClassification(doc.id, result.data);
        setNotice(`Confirmed ${doc.filename} as ${docType}`);
      } else if (!result.disconnected && result.error.code === "not_found") {
        // The backend answers a non-admin with 404 rather than 403, so it
        // says nothing about whether the document exists. This is the ONE
        // sentence in the app that treats a 404 here as "you may not do
        // this" rather than "gone" - see `classification.confirm`.
        setNotice("You do not have permission to confirm this document's type.");
      } else {
        setNotice(`Could not confirm the type for ${doc.filename}. Try again.`);
      }
    },
    [setOneClassification],
  );

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

  // Nothing ticked = no filter = show everything. Ticking narrows what is on
  // screen ALREADY LOADED - no new request, because the corpus this filter
  // narrows is the one `load.documents` already holds.
  const passesFilter = useCallback(
    (doc: DocumentRecord) => {
      if (selectedTypes.length === 0) return true;
      const t = typeOf(doc, classifications);
      return t === null ? selectedTypes.includes(AWAITING_TYPE) : selectedTypes.includes(t);
    },
    [selectedTypes, classifications],
  );

  return (
    <div className="aurora-field space-y-6">
      <div aria-hidden className="aurora-a" />
      <div aria-hidden className="aurora-b" />
      <header>
        <h1 className="text-xl font-semibold text-slateish-200">Documents</h1>
        <p className="mt-1 text-sm text-slateish-400">
          Upload, inspect, and verify what the system can actually search.
        </p>
      </header>

      <div className="flex flex-wrap items-end gap-3 rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-3">
        <label className="min-w-56 flex-1 text-xs font-semibold uppercase tracking-wide text-slateish-400">
          Find documents
          <input value={listQuery} onChange={(e) => setListQuery(e.target.value)} placeholder="Filename contains…" className="mt-1 w-full rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-3 py-2 text-sm font-normal text-slateish-200" />
        </label>
        <label className="text-xs font-semibold uppercase tracking-wide text-slateish-400">Sort
          <select value={sort} onChange={(e) => setSort(e.target.value)} className="mt-1 block rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-3 py-2 text-sm font-normal text-slateish-200">
            <option value="uploaded_at">Newest</option><option value="filename">Filename</option><option value="status">Status</option>
          </select>
        </label>
        <button type="button" className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-2 text-sm" onClick={() => setDirection((d) => d === "asc" ? "desc" : "asc")}>Order: {direction === "asc" ? "A–Z" : "Newest"}</button>
      </div>

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

      {/* THE TYPE FILTER. Built here rather than with <TypeFilter> because
          that component's "documents in scope" count is the SERVER'S echo of
          a search it just ran - it does not apply to a list already sitting
          on screen. This filter never leaves the browser. */}
      {vocabulary && vocabulary.types.length > 0 && load.state === "ready" && (
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="me-1 text-xs font-semibold uppercase tracking-wide text-slateish-400">
              Type
            </span>
            <FilterChip
              label="All"
              on={selectedTypes.length === 0}
              onClick={clearTypes}
            />
            {vocabulary.types.map((type) => (
              <FilterChip
                key={type}
                label={type}
                count={vocabulary.countByType[type]}
                on={selectedTypes.includes(type)}
                onClick={() => toggleType(type)}
              />
            ))}
            <FilterChip
              label={AWAITING_TYPE_LABEL}
              count={vocabulary.needsClassification}
              on={selectedTypes.includes(AWAITING_TYPE)}
              onClick={() => toggleType(AWAITING_TYPE)}
              amber
            />
          </div>
          {/* A count with no stated boundary reads as total. `corpus_wide` is
              true only for an admin - everyone else's counts above are their
              own grants, and this line is the one place that says so. */}
          <p className="text-xs text-slateish-500">
            {vocabulary.corpusWide
              ? "Counts cover every document in the corpus."
              : "Counts cover the documents you can open."}
          </p>
        </div>
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

        {load.state === "ready" &&
          load.documents.length > 0 &&
          !classificationsReady && <Spinner label="Loading document classifications" />}

        {load.state === "ready" && load.documents.length > 0 && classificationsReady && (
          <div className="space-y-6">
            {(() => {
              const filtered = load.documents.filter(passesFilter);
              const types = vocabulary?.types ?? [];
              const { groups, awaiting } = groupByType(filtered, types, classifications);
              const showType = (name: string) =>
                selectedTypes.length === 0 || selectedTypes.includes(name);
              const showAwaiting = selectedTypes.length === 0 || selectedTypes.includes(AWAITING_TYPE);

              return (
                <>
                  {groups
                    .filter((g) => showType(g.name))
                    .map((group) => (
                      <div key={group.name}>
                        <h3
                          className="mb-2 flex items-baseline gap-2 text-xs font-semibold uppercase tracking-wider text-slateish-400"
                          aria-label={`${group.name}, ${group.documents.length} document(s)`}
                        >
                          {group.name}
                          <span className="font-mono text-slateish-500">
                            {group.documents.length}
                          </span>
                        </h3>
                        {group.documents.length === 0 ? (
                          // RULE: a type that exists in the register but has
                          // no document this caller can read gets an honest
                          // line, not a vanished heading. Only an admin's
                          // corpus-wide counts license the stronger claim
                          // that none exist at all.
                          <p className="text-sm text-slateish-500">
                            {vocabulary?.corpusWide
                              ? `There are no ${group.name} documents.`
                              : `None of the documents you can open is a ${group.name}.`}
                          </p>
                        ) : (
                          <ul className="virtual-list space-y-3">
                            {group.documents.map((doc) => (
                              <DocumentCard
                                key={doc.id}
                                doc={doc}
                                actions={actions}
                                classification={classifications[doc.id]}
                                types={types}
                                isAdmin={isAdmin}
                                onConfirmType={confirmType}
                              />
                            ))}
                          </ul>
                        )}
                      </div>
                    ))}

                  {showAwaiting && awaiting.documents.length > 0 && (
                    <div key={awaiting.name}>
                      <h3
                        className="mb-2 flex items-baseline gap-2 text-xs font-semibold uppercase tracking-wider text-warn-500"
                        aria-label={`${awaiting.name}, ${awaiting.documents.length} document(s)`}
                      >
                        {awaiting.name}
                        <span className="font-mono text-warn-500/70">
                          {awaiting.documents.length}
                        </span>
                      </h3>
                      <ul className="virtual-list space-y-3">
                        {awaiting.documents.map((doc) => (
                          <DocumentCard
                            key={doc.id}
                            doc={doc}
                            actions={actions}
                            classification={classifications[doc.id]}
                            types={types}
                            isAdmin={isAdmin}
                            onConfirmType={confirmType}
                          />
                        ))}
                      </ul>
                    </div>
                  )}
                  {totalMatching !== null && totalMatching > load.documents.length && (
                    <div className="flex items-center justify-between border-t border-ink-700 pt-4">
                      <p className="text-sm text-slateish-400">Showing {load.documents.length} of {totalMatching} documents.</p>
                      <button type="button" onClick={() => void loadMore()} className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-2 text-sm">Load next 100</button>
                    </div>
                  )}
                </>
              );
            })()}
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

function FilterChip({
  label,
  count,
  on,
  onClick,
  amber,
}: {
  label: string;
  count?: number;
  on: boolean;
  onClick: () => void;
  amber?: boolean;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={on}
      onClick={onClick}
      className={[
        "inline-flex items-center gap-2 rounded-[var(--radius-full)] border px-2.5 py-1 text-[13px] motion-safe:transition-colors",
        on
          ? amber
            ? "border-warn-500/50 bg-warn-500/10 text-warn-500"
            : "border-signal-500/40 bg-signal-500/10 text-signal-400"
          : amber
            ? "border-warn-500/30 bg-ink-800 text-warn-500/80 hover:bg-warn-500/10"
            : "border-ink-600 bg-ink-800 text-slateish-300 hover:bg-ink-700",
      ].join(" ")}
    >
      {label}
      {/* A COUNT ONLY WHEN COVERAGE ANSWERED. See TypeFilter.tsx: rendering 0
          for "we do not know" reads as "there are none of these". */}
      {count != null && <span className="font-mono text-xs text-slateish-300">{count}</span>}
    </button>
  );
}
