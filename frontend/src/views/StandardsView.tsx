/**
 * The Standards Library.
 *
 * A DEDICATED LIBRARY OVER THE SAME STORAGE AND THE SAME PERMISSIONS. Every
 * row here is a document in the one database, read under the caller's grants
 * through `GET /api/standards`. "Separate library" is a statement about what a
 * reader sees, never about where the bytes live - there is no second database
 * and no second retrieval path.
 *
 * WHAT IT REFUSES TO SAY:
 *  - A standard with no extracted requirements says **0 extracted**, never
 *    "none required" and never a readiness tick. Zero is a real answer about
 *    what has been read, not a statement about the standard.
 *  - A superseded standard is shown as superseded and stays openable. It is
 *    excluded from SELECTION for new reviews, which is a different question
 *    from whether it may be read - an engineer must still be able to open the
 *    revision a submittal was reviewed against last year.
 *  - Null renders as nothing. Most of these fields are null until someone
 *    records them.
 *
 * Applicability is Phase 3B and is deliberately absent - including from the
 * tab strip, because an empty tab reads as a broken feature rather than an
 * unbuilt one.
 */
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import { DocumentPreview } from "../components/DocumentPreview";
import { EmptyState, ErrorState, Spinner } from "../components/states";
import type {
  ApiError, DocumentRecord, StandardRequirement, StandardSummary,
} from "../types/api";

type Load =
  | { state: "loading" }
  | { state: "error"; error: ApiError; disconnected: boolean }
  | { state: "ready"; standards: StandardSummary[] };

type Tab = "document" | "requirements" | "revisions" | "processing";

const TABS: ReadonlyArray<{ id: Tab; label: string }> = [
  { id: "document", label: "Original Document" },
  { id: "requirements", label: "Requirements" },
  { id: "revisions", label: "Revision History" },
  { id: "processing", label: "Processing Details" },
];

export function StandardsView({ isAdmin = false }: { isAdmin?: boolean }) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [selected, setSelected] = useState<StandardSummary | null>(null);
  const [includeSuperseded, setIncludeSuperseded] = useState(true);

  const refresh = useCallback(async () => {
    const result = await api.standards({ include_superseded: includeSuperseded });
    if (result.ok) setLoad({ state: "ready", standards: result.data });
    else setLoad({ state: "error", error: result.error, disconnected: result.disconnected });
  }, [includeSuperseded]);

  useEffect(() => { void refresh(); }, [refresh]);

  if (load.state === "loading") return <Spinner />;
  if (load.state === "error") {
    return <ErrorState error={load.error} onRetry={() => void refresh()} />;
  }

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-medium">Standards Library</h2>
        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={includeSuperseded}
            onChange={(e) => setIncludeSuperseded(e.target.checked)}
          />
          Show superseded
        </label>
      </header>

      {load.standards.length === 0 ? (
        <EmptyState
          title="No standards yet"
          hint="A document appears here once an administrator sets its role to Company standard."
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {load.standards.map((standard) => (
            <li key={standard.id}>
              <StandardRow
                standard={standard}
                onOpen={() => setSelected(standard)}
              />
            </li>
          ))}
        </ul>
      )}

      {selected && (
        <StandardDetail
          standard={selected}
          isAdmin={isAdmin}
          onClose={() => setSelected(null)}
          onChanged={() => void refresh()}
        />
      )}
    </div>
  );
}

/** One row of the library. */
function StandardRow({
  standard, onOpen,
}: { standard: StandardSummary; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full rounded border border-white/10 bg-white/[0.02] p-3 text-left"
    >
      <div className="flex flex-wrap items-center gap-2">
        {/* The number is how an engineer names a standard. Falls back to the
            filename rather than rendering an empty heading. */}
        <span className="font-medium">{standard.document_number || standard.filename}</span>
        {standard.revision && (
          <span className="rounded bg-white/10 px-2 py-0.5 text-xs">Rev {standard.revision}</span>
        )}
        {standard.superseded ? (
          <span className="rounded bg-warn-500/20 px-2 py-0.5 text-xs text-warn-500">
            Superseded
          </span>
        ) : (
          <span className="rounded bg-signal-500/20 px-2 py-0.5 text-xs text-signal-400">
            Active
          </span>
        )}
        {/* THE CANONICAL SPELLING, WITH THE DOCUMENT'S OWN IN THE TOOLTIP.
            "Non-metallic" and "Nonmetallic" are one discipline written two
            ways, and a library that lists both teaches a reader they are two.
            The raw value is still reachable, because it is what the cover
            page actually says - and the tooltip appears ONLY when the two
            differ, so an unmapped value carries no pointless hover. */}
        {(standard.discipline_canonical || standard.discipline) && (
          <span
            className="rounded bg-white/5 px-2 py-0.5 text-xs"
            title={
              standard.discipline
              && standard.discipline_canonical
              && standard.discipline !== standard.discipline_canonical
                ? `the document says "${standard.discipline}"`
                : undefined
            }
          >
            {standard.discipline_canonical || standard.discipline}
          </span>
        )}
      </div>
      {standard.title && <p className="mt-1 text-xs opacity-80">{standard.title}</p>}
      <p className="mt-1 text-xs opacity-70">
        {standard.effective_date && <>Effective {standard.effective_date} · </>}
        {/* ZERO IS A REAL ANSWER and is worded as one. "0 requirements" would
            read as "this standard requires nothing". */}
        {standard.requirement_count === 0
          ? "No requirements extracted yet"
          : `${standard.requirement_count} requirement${standard.requirement_count === 1 ? "" : "s"}`}
        {standard.awaiting_verification > 0 && (
          <span className="text-warn-500">
            {" "}· {standard.awaiting_verification} awaiting verification
          </span>
        )}
      </p>
    </button>
  );
}

function StandardDetail({
  standard, isAdmin, onClose, onChanged,
}: {
  standard: StandardSummary;
  isAdmin: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [tab, setTab] = useState<Tab>("requirements");

  return (
    <section
      aria-label={`Standard ${standard.document_number || standard.filename}`}
      className="rounded border border-white/15 p-3"
    >
      <header className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-medium">
          {standard.document_number || standard.filename}
        </h3>
        <button type="button" onClick={onClose} className="text-xs underline">
          Close
        </button>
      </header>

      <div role="tablist" aria-label="Standard detail" className="mt-2 flex flex-wrap gap-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`rounded px-2 py-1 text-xs ${tab === t.id ? "bg-white/15" : "bg-white/5"}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="mt-3">
        {tab === "document" && (
          <DocumentPreview doc={asDocument(standard)} />
        )}
        {tab === "requirements" && (
          <RequirementsTab standard={standard} isAdmin={isAdmin} onExtracted={onChanged} />
        )}
        {tab === "revisions" && <RevisionsTab standard={standard} isAdmin={isAdmin} onChanged={onChanged} />}
        {tab === "processing" && <ProcessingTab standard={standard} />}
      </div>
    </section>
  );
}

/** The library row carries only what the list needs; the preview wants a
 *  document. Built here rather than fetched again, and every field the preview
 *  does not read is left at its honest empty value. */
function asDocument(standard: StandardSummary): DocumentRecord {
  return {
    id: standard.id, filename: standard.filename, sha256: "", size_bytes: 0,
    page_count: standard.page_count, pages_done: 0, chunk_count: 0,
    chunk_count_total: 0, disciplines: [], embedded_count: 0,
    status: standard.status, needs_ocr_pages: 0, recognised_pages: 0,
    equation_pages: 0, error: null, uploaded_at: standard.uploaded_at,
    indexed_at: null, title: standard.title, revision: standard.revision,
    document_number: standard.document_number, document_role: "COMPANY_STANDARD",
    superseded_by: standard.superseded_by,
  };
}

function RequirementsTab({
  standard, isAdmin, onExtracted,
}: { standard: StandardSummary; isAdmin: boolean; onExtracted: () => void }) {
  const [rows, setRows] = useState<StandardRequirement[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const result = await api.standardRequirements(standard.id);
    if (result.ok) setRows(result.data);
    else setError(result.error.message);
  }, [standard.id]);

  useEffect(() => { void load(); }, [load]);

  const extract = async () => {
    setBusy(true); setError(null);
    const result = await api.extractStandardRequirements(standard.id);
    setBusy(false);
    if (!result.ok) { setError(result.error.message); return; }
    await load();
    onExtracted();
  };

  if (rows === null) return <Spinner />;

  return (
    <div className="flex flex-col gap-3">
      {isAdmin && (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => void extract()}
            disabled={busy}
            className="rounded bg-white/15 px-3 py-1 text-xs disabled:opacity-50"
          >
            {busy ? "Reading the standard…" : "Extract requirements"}
          </button>
          {error && <span role="alert" className="text-xs text-warn-500">{error}</span>}
        </div>
      )}

      {rows.length === 0 ? (
        // NOT "this standard has no requirements". It has not been read yet,
        // and those are completely different statements.
        <p className="text-xs opacity-70">
          No requirements have been extracted from this standard yet.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((row) => (
            <li key={row.id} className="rounded border border-white/10 p-2 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                {/* A clause the parser could not identify renders as exactly
                    that. Never a guessed number. */}
                <span className="font-mono">
                  {row.clause ?? "Clause not identified"}
                </span>
                {row.page != null && <span className="opacity-70">page {row.page}</span>}
                {row.needs_verification && (
                  <span className="rounded bg-warn-500/20 px-2 py-0.5 text-warn-500">
                    Awaiting verification
                  </span>
                )}
                {row.extraction_method === "extracted" && !row.confirmed_by && (
                  <span className="rounded bg-white/10 px-2 py-0.5 opacity-80">
                    Extracted, not confirmed
                  </span>
                )}
                {!row.citation_resolves && (
                  <span role="alert" className="rounded bg-danger-500/20 px-2 py-0.5 text-danger-500">
                    Citation no longer resolves - re-extract
                  </span>
                )}
              </div>
              <p className="mt-1">{row.requirement_text}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RevisionsTab({
  standard, isAdmin, onChanged,
}: { standard: StandardSummary; isAdmin: boolean; onChanged: () => void }) {
  const [rows, setRows] = useState<StandardSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const result = await api.standardRevisions(standard.id);
    if (result.ok) setRows(result.data);
    else setError(result.error.message);
  }, [standard.id]);

  useEffect(() => { void load(); }, [load]);

  const supersede = async (by: string | null) => {
    setError(null);
    const result = await api.supersedeStandard(standard.id, by);
    if (!result.ok) { setError(result.error.message); return; }
    await load();
    onChanged();
  };

  if (rows === null) return <Spinner />;

  const others = rows.filter((r) => r.id !== standard.id);

  return (
    <div className="flex flex-col gap-3">
      {rows.length <= 1 && (
        <p className="text-xs opacity-70">
          No other revisions of this standard number are in the library.
        </p>
      )}
      <ul className="flex flex-col gap-1">
        {rows.map((row) => (
          <li key={row.id} className="flex flex-wrap items-center gap-2 text-xs">
            <span className="font-mono">{row.revision ?? "revision not recorded"}</span>
            {row.effective_date && <span className="opacity-70">{row.effective_date}</span>}
            {row.superseded ? (
              <span className="text-warn-500">superseded</span>
            ) : (
              <span className="text-signal-400">active</span>
            )}
            {row.id === standard.id && <span className="opacity-60">(this one)</span>}
          </li>
        ))}
      </ul>

      {isAdmin && (
        <div className="flex flex-col gap-2 border-t border-white/10 pt-2">
          <label className="flex flex-col gap-1 text-xs">
            <span className="opacity-80">Superseded by</span>
            <select
              aria-label="Superseded by"
              value={standard.superseded_by ?? ""}
              onChange={(e) => void supersede(e.target.value === "" ? null : e.target.value)}
              className="rounded border border-white/15 bg-transparent px-2 py-1"
            >
              <option value="">Not superseded</option>
              {others.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.document_number || row.filename}
                  {row.revision ? ` Rev ${row.revision}` : ""}
                </option>
              ))}
            </select>
          </label>
          <p className="text-xs opacity-70">
            A superseded standard stops being selected for new reviews. It stays
            readable and citable.
          </p>
          {error && <span role="alert" className="text-xs text-warn-500">{error}</span>}
        </div>
      )}
    </div>
  );
}

function ProcessingTab({ standard }: { standard: StandardSummary }) {
  const [clauses, setClauses] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api.standardClauses(standard.id).then((result) => {
      if (!cancelled && result.ok) setClauses(result.data.length);
    });
    return () => { cancelled = true; };
  }, [standard.id]);

  return (
    <dl className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-3">
      <Field label="Processing status" value={standard.status.replace(/_/g, " ")} />
      <Field label="Pages" value={standard.page_count} />
      <Field label="Clauses detected" value={clauses} />
      <Field label="Requirements extracted" value={standard.requirement_count} />
      <Field label="Awaiting verification" value={standard.awaiting_verification} />
      <Field label="Uploaded" value={standard.uploaded_at} />
    </dl>
  );
}

/** Null renders as nothing. A COUNT of 0 is shown, because on this tab zero
 *  clauses is a measurement of what the parser found and the reader needs to
 *  see it - unlike a null, which means nobody has looked. */
function Field({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex flex-col">
      <dt className="text-[11px] uppercase tracking-wide opacity-60">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
