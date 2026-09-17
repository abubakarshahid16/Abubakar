/**
 * One document in the list.
 *
 * Three presentation rules that exist because the backend got them wrong:
 *  - never "ready" until embedding has finished
 *  - `no_searchable_content` is a warning with its reason, never a success
 *  - a low retrievable ratio is loud, with one click through to the excluded
 *    viewer, because a quality gate over-rejecting an unfamiliar layout is
 *    otherwise completely silent
 */
import { useState } from "react";

import type { ClassificationSource, DocumentClassification, DocumentRecord } from "../types/api";
import {
  LOW_RETRIEVABLE_THRESHOLD,
  embedProgress,
  excludedCount,
  hasLowRetrievableRatio,
  presentStatus,
  progressLine,
  retrievableRatio,
} from "./documentStatus";

const TONE: Record<string, string> = {
  neutral: "bg-ink-700 text-slateish-300",
  progress: "bg-info-500/20 text-info-500",
  success: "bg-signal-500/20 text-signal-400",
  warning: "bg-warn-500/20 text-warn-500",
  danger: "bg-danger-500/20 text-danger-500",
};

const nf = new Intl.NumberFormat("en-GB");

export interface DocumentActions {
  onInspect: (doc: DocumentRecord) => void;
  onExcluded: (doc: DocumentRecord) => void;
  onPages: (doc: DocumentRecord) => void;
  onExtract: (doc: DocumentRecord) => void;
  onChunk: (doc: DocumentRecord) => void;
  onEmbed: (doc: DocumentRecord) => void;
  onDelete: (doc: DocumentRecord) => void;
  busy: string | null;
}

export function DocumentCard({
  doc,
  actions,
  classification,
  types,
  isAdmin = false,
  onConfirmType,
}: {
  doc: DocumentRecord;
  actions: DocumentActions;
  /** This document's classification. Absent (not `null`) while it has not
   *  answered yet - see `useDocumentClassifications`, which is the only
   *  thing that ever supplies this prop. */
  classification?: DocumentClassification;
  /** The register's type names, for the "change type" picker. Never a
   *  hardcoded list - see `TypeFilter.tsx` for why. */
  types?: string[];
  /** Whether the confirm control may appear at all. The control must never
   *  render for a caller who cannot use it: `classification.confirm` 404s a
   *  non-admin, and a button that always 404s is worse than no button. */
  isAdmin?: boolean;
  /** Confirms (or changes) this document's type. Absent classification or no
   *  admin means this is never called - see the render logic below. */
  onConfirmType?: (doc: DocumentRecord, docType: string) => void;
}) {
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [showStages, setShowStages] = useState(false);
  const [changingType, setChangingType] = useState(false);
  const status = presentStatus(doc);
  const ratio = retrievableRatio(doc);
  const excluded = excludedCount(doc);
  const progress = embedProgress(doc);
  const busy = actions.busy === doc.id;

  return (
    <li className="card-3d surface-card rounded-[var(--radius-md)] border border-ink-700 bg-ink-850">
      <div className="flex flex-wrap items-start justify-between gap-3 p-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate font-medium text-slateish-200">{doc.filename}</h3>
            <span className={`rounded-[var(--radius-xs)] px-2 py-0.5 text-[11px] ${TONE[status.tone]}`}>
              {status.label}
            </span>
            {/* THE REGISTER TYPE. NEUTRAL only when `confirmed` is true - a
                human has agreed with it. Everything else, including a
                document with no suggested type at all, is amber or muted:
                `confirmed: false` means a machine guessed and nobody has
                signed off, and that must be visible on the card itself, not
                buried in a drawer. Absent `classification` (still loading)
                renders nothing here rather than a placeholder chip. */}
            {classification &&
              (classification.doc_type === null ? (
                <span
                  data-testid="type-chip"
                  className="rounded-[var(--radius-xs)] border border-ink-600 px-2 py-0.5 text-[11px] text-slateish-400"
                >
                  Awaiting a type
                </span>
              ) : classification.confirmed ? (
                <span
                  data-testid="type-chip"
                  className="rounded-[var(--radius-xs)] bg-ink-700 px-2 py-0.5 text-[11px] text-slateish-300"
                >
                  {classification.doc_type}
                </span>
              ) : (
                <span
                  data-testid="type-chip"
                  className="rounded-[var(--radius-xs)] border border-warn-500/40 bg-warn-500/10 px-2 py-0.5 text-[11px] text-warn-500"
                  title={`Suggested by ${classification.suggested_by}, not yet confirmed.`}
                >
                  {`${classification.doc_type}? \u00b7 guessed from ${sourceLabel(classification.suggested_by)}`}
                </span>
              ))}
            {/* THE CATEGORY. It is the access grant - plan line 1010 makes
                discipline the grant rather than a tag - so this reads the
                grant tables through the API and never infers from the
                filename. An EMPTY list is a real state, not missing data: no
                discipline holds this document and only an administrator can
                read it. It is labelled as exactly that, never left blank and
                never given a placeholder. */}
            {doc.disciplines.length > 0 ? (
              doc.disciplines.map((d) => (
                <span
                  key={d}
                  data-testid="discipline"
                  className="rounded-[var(--radius-xs)] border border-signal-500/40 bg-signal-500/10 px-2 py-0.5 text-[11px] text-signal-400"
                >
                  {d}
                </span>
              ))
            ) : (
              <span
                data-testid="discipline"
                className="rounded-[var(--radius-xs)] border border-ink-600 px-2 py-0.5 text-[11px] text-slateish-400"
                title="No discipline holds this document. Only an administrator can read it."
              >
                Admin only
              </span>
            )}
{/* Amber ONLY while pages are still unread. A document being partly
                OCR'd is a capability working, not a problem - once recognition
                has covered the scanned pages this badge disappears and the
                fact moves to the facts line below, where it belongs. The old
                tooltip said "OCR is not implemented", which stopped being true
                the day it shipped. */}
            {doc.needs_ocr_pages > doc.recognised_pages && (
              <span
                className="rounded-[var(--radius-xs)] bg-warn-500/15 px-2 py-0.5 text-[11px] text-warn-500"
                title="Scanned pages with no extractable text that recognition has not yet read."
              >
                {doc.needs_ocr_pages - doc.recognised_pages} awaiting OCR
              </span>
            )}
            {doc.equation_pages > 0 && (
              <span
                className="rounded-[var(--radius-xs)] bg-info-500/15 px-2 py-0.5 text-[11px] text-info-500"
                title="Mathematics did not survive extraction on these pages. Use the page image."
              >
                {doc.equation_pages} equation-heavy
              </span>
            )}
          </div>

          <p className="mt-1 font-mono text-xs text-slateish-400">{progressLine(doc)}</p>

          {doc.chunk_count > 0 && doc.embedded_count < doc.chunk_count && (
            <div
              className="mt-2 h-1.5 w-full max-w-md overflow-hidden rounded-[var(--radius-xs)] bg-ink-700"
              role="progressbar"
              aria-label={`Embedding ${doc.filename}`}
              aria-valuenow={Math.round(progress * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className="h-full bg-info-500 transition-all"
                style={{ width: `${progress * 100}%` }}
              />
            </div>
          )}

          <p className="mt-2 text-xs text-slateish-400">
            {nf.format(doc.chunk_count)} searchable of {nf.format(doc.chunk_count_total)} chunks
            {excluded > 0 && <> · {nf.format(excluded)} excluded</>}
            {/* A FACT, not a badge. "12 of 546 pages read by OCR" tells the
                reader what happened; an amber pill would tell them something
                is wrong, and nothing is. Stated as a fraction because a bare
                count invites reading a 546-page document as an OCR'd one. */}
            {doc.recognised_pages > 0 && doc.page_count != null && (
              <>
                {" "}
                · {nf.format(doc.recognised_pages)} of {nf.format(doc.page_count)} pages
                read by OCR
              </>
            )}
            {doc.indexed_at && <> · finished {doc.indexed_at.replace("T", " ").replace("Z", "")}</>}
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap gap-1.5">
          {/* "passages", the word the Dashboard defines. The same object was
              called sections, chunks and passages across three screens, and
              "inspect" and "stages" are developer vocabulary. */}
          <Action label="Passages" onClick={() => actions.onInspect(doc)} primary />
          <Action label="Excluded" onClick={() => actions.onExcluded(doc)} />
          <Action label="Pages" onClick={() => actions.onPages(doc)} />
          {/* Re-running a stage is a maintenance operation, not a reading one.
              On a 1,400-page document each of these is minutes of compute, and
              they sat one keystroke apart from the reading controls where a
              stray Enter reached them. They stay available and stay honest -
              just not in the path of someone looking at their document. */}
          <Action
            label={showStages ? "Hide processing" : "Processing"}
            onClick={() => setShowStages((v) => !v)}
            expanded={showStages}
          />
          {showStages && (
            <>
              <Action label="Extract" onClick={() => actions.onExtract(doc)} disabled={busy} />
              <Action label="Chunk" onClick={() => actions.onChunk(doc)} disabled={busy} />
              <Action label="Embed" onClick={() => actions.onEmbed(doc)} disabled={busy} />
            </>
          )}
          {confirmingDelete ? (
            <>
              <Action
                label="Confirm delete"
                onClick={() => {
                  setConfirmingDelete(false);
                  actions.onDelete(doc);
                }}
                danger
              />
              <Action label="Cancel" onClick={() => setConfirmingDelete(false)} />
            </>
          ) : (
            <Action label="Delete" onClick={() => setConfirmingDelete(true)} danger />
          )}
        </div>
      </div>

      {/* THE CONFIRM STRIP. Only for a classification that has not been
          confirmed - a plain neutral chip above needs no action here. The
          control itself only ever appears for an admin: `classification.
          confirm` answers a non-admin with a 404 that says nothing about
          whether the document exists, so a button that always fails is
          strictly worse than the sentence below it. */}
      {classification && !classification.confirmed && (
        <div className="border-t border-warn-500/20 bg-warn-500/5 px-4 py-2.5 text-xs">
          {isAdmin ? (
            changingType || classification.doc_type === null ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-slateish-400">
                  {classification.doc_type === null ? "Set the type:" : "Change to:"}
                </span>
                {(types ?? []).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => {
                      setChangingType(false);
                      onConfirmType?.(doc, t);
                    }}
                    className="rounded-[var(--radius-xs)] border border-ink-600 px-2 py-1 text-slateish-300 hover:bg-ink-700"
                  >
                    {t}
                  </button>
                ))}
                {classification.doc_type !== null && (
                  <button
                    type="button"
                    onClick={() => setChangingType(false)}
                    className="text-slateish-500 hover:text-slateish-300"
                  >
                    Cancel
                  </button>
                )}
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <Action
                  label="Confirm"
                  onClick={() => onConfirmType?.(doc, classification.doc_type as string)}
                  primary
                />
                <Action label="Change" onClick={() => setChangingType(true)} />
              </div>
            )
          ) : (
            <p className="text-slateish-400">Awaiting confirmation by an administrator.</p>
          )}
        </div>
      )}

      {status.tone === "warning" && doc.error && (
        <div role="alert" className="border-t border-warn-500/30 bg-warn-500/10 px-4 py-3 text-sm">
          <p className="font-medium text-warn-500">Nothing on this document is searchable</p>
          <p className="mt-1 text-slateish-300">{doc.error.message}</p>
        </div>
      )}

      {doc.status === "failed" && doc.error && (
        <div role="alert" className="border-t border-danger-500/30 bg-danger-500/10 px-4 py-3 text-sm">
          <p className="font-medium text-danger-500">Processing failed</p>
          <p className="mt-1 text-slateish-300">{doc.error.message}</p>
          <p className="mt-1 font-mono text-xs text-slateish-400">code: {doc.error.code}</p>
        </div>
      )}

      {/* Excluded PAGES. A page search cannot see at all is a different and
          worse thing than an excluded chunk, and it was being reported as a
          quiet number beside the chunk count - "3 excluded" - which neither
          the operator nor the client looked at. On NORSOK that quiet number
          was an entire clause. */}
      {(doc.pages_excluded ?? 0) > 0 && (
        <div
          role={(doc.pages_excluded_with_clause_headings ?? 0) > 0 ? "alert" : "status"}
          className={[
            "border-t px-4 py-3 text-sm",
            // COLOUR MEANS SOMETHING AGAIN. Twelve of thirteen cards were
            // wrapped in an amber block for the routine exclusion of front
            // matter and contents pages, so the one card with a dropped CLAUSE
            // - the thing this block exists to flag - looked exactly like the
            // rest. Routine is quiet; a dropped clause is the only coloured one.
            (doc.pages_excluded_with_clause_headings ?? 0) > 0
              ? "border-danger-500/40 bg-danger-500/10"
              : "border-ink-700 bg-transparent",
          ].join(" ")}
        >
          {(doc.pages_excluded_with_clause_headings ?? 0) > 0 ? (
            <>
              <p className="font-medium text-danger-500">
                {nf.format(doc.pages_excluded_with_clause_headings ?? 0)} excluded page
                {(doc.pages_excluded_with_clause_headings ?? 0) === 1 ? "" : "s"} contain
                numbered clause headings
              </p>
              <p className="mt-1 text-slateish-300">
                A page with numbered clauses and real prose is body text. Real
                content has almost certainly been dropped and will not be
                found by any question. Check this before relying on answers
                from this document.
              </p>
            </>
          ) : (
            <>
              <p className="text-slateish-300">
                <span className="font-medium text-slateish-200">
                  {nf.format(doc.pages_excluded ?? 0)} page
                  {(doc.pages_excluded ?? 0) === 1 ? "" : "s"} left out of search
                </span>
                <span className="text-slateish-400">
                  {" "}&mdash; contents pages, front matter and the like, excluded on purpose.
                  No numbered clause was among them.
                </span>
              </p>
            </>
          )}
          <button
            type="button"
            onClick={() => actions.onExcluded(doc)}
            className={[
              "mt-2 rounded-[var(--radius-xs)] border px-3 py-1 text-xs",
              (doc.pages_excluded_with_clause_headings ?? 0) > 0
                ? "border-danger-500/60 text-danger-500 hover:bg-danger-500/15"
                : "border-ink-500 text-slateish-300 hover:bg-ink-700",
            ].join(" ")}
          >
            See which pages, and why
          </button>
        </div>
      )}

      {hasLowRetrievableRatio(doc) && ratio !== null && (
        <div
          role="alert"
          className="border-t border-warn-500/30 bg-warn-500/10 px-4 py-3 text-sm"
        >
          <p className="font-medium text-warn-500">
            Only {Math.round(ratio * 100)}% of this document is searchable
          </p>
          <p className="mt-1 text-slateish-300">
            {nf.format(excluded)} of {nf.format(doc.chunk_count_total)} chunks were excluded —
            below the {Math.round(LOW_RETRIEVABLE_THRESHOLD * 100)}% threshold. If this layout is
            unfamiliar, the quality gate may be over-rejecting it.
          </p>
          <button
            type="button"
            onClick={() => actions.onExcluded(doc)}
            className="mt-2 rounded-[var(--radius-xs)] border border-warn-500/60 px-3 py-1 text-xs text-warn-500 hover:bg-warn-500/15"
          >
            See what was excluded
          </button>
        </div>
      )}
    </li>
  );
}

/** What a machine-suggested classification is guessed FROM, in the reader's
 *  words rather than the wire value. `register` never reaches here - it is
 *  the one client-authoritative tier and is confirmed on arrival. Exhaustive
 *  over `ClassificationSource` so a rename on the backend (`pattern` was
 *  `filename`/`content` on the wire until the contract was corrected to match
 *  it) fails the build here instead of silently falling through to the raw
 *  wire word. */
function sourceLabel(source: ClassificationSource): string {
  switch (source) {
    case "pattern":
      return "the filename and content";
    case "register":
      return "the register";
    case "none":
      return "nothing";
  }
}

function Action({
  label,
  onClick,
  disabled,
  primary,
  danger,
  expanded,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
  danger?: boolean;
  expanded?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-expanded={expanded}
      className={[
        "rounded-[var(--radius-xs)] border px-2.5 py-1 text-xs transition-colors disabled:opacity-40",
        primary
          ? "border-signal-500/60 text-signal-400 hover:bg-signal-500/15"
          : danger
            ? "border-danger-500/50 text-danger-500 hover:bg-danger-500/15"
            : "border-ink-600 text-slateish-300 hover:bg-ink-700",
      ].join(" ")}
    >
      {label}
    </button>
  );
}
