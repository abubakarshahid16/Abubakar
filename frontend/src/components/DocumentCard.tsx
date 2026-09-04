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

import type { DocumentRecord } from "../types/api";
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
}: {
  doc: DocumentRecord;
  actions: DocumentActions;
}) {
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [showStages, setShowStages] = useState(false);
  const status = presentStatus(doc);
  const ratio = retrievableRatio(doc);
  const excluded = excludedCount(doc);
  const progress = embedProgress(doc);
  const busy = actions.busy === doc.id;

  return (
    <li className="rounded-lg border border-ink-700 bg-ink-850">
      <div className="flex flex-wrap items-start justify-between gap-3 p-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate font-medium text-slateish-200">{doc.filename}</h3>
            <span className={`rounded px-2 py-0.5 text-[11px] ${TONE[status.tone]}`}>
              {status.label}
            </span>
{/* Amber ONLY while pages are still unread. A document being partly
                OCR'd is a capability working, not a problem - once recognition
                has covered the scanned pages this badge disappears and the
                fact moves to the facts line below, where it belongs. The old
                tooltip said "OCR is not implemented", which stopped being true
                the day it shipped. */}
            {doc.needs_ocr_pages > doc.recognised_pages && (
              <span
                className="rounded bg-warn-500/15 px-2 py-0.5 text-[11px] text-warn-500"
                title="Scanned pages with no extractable text that recognition has not yet read."
              >
                {doc.needs_ocr_pages - doc.recognised_pages} awaiting OCR
              </span>
            )}
            {doc.equation_pages > 0 && (
              <span
                className="rounded bg-info-500/15 px-2 py-0.5 text-[11px] text-info-500"
                title="Mathematics did not survive extraction on these pages. Use the page image."
              >
                {doc.equation_pages} equation-heavy
              </span>
            )}
          </div>

          <p className="mt-1 font-mono text-xs text-slateish-400">{progressLine(doc)}</p>

          {doc.chunk_count > 0 && doc.embedded_count < doc.chunk_count && (
            <div
              className="mt-2 h-1.5 w-full max-w-md overflow-hidden rounded bg-ink-700"
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
          <Action label="Inspect chunks" onClick={() => actions.onInspect(doc)} primary />
          <Action label="Excluded" onClick={() => actions.onExcluded(doc)} />
          <Action label="Pages" onClick={() => actions.onPages(doc)} />
          {/* Re-running a stage is a maintenance operation, not a reading one.
              On a 1,400-page document each of these is minutes of compute, and
              they sat one keystroke apart from the reading controls where a
              stray Enter reached them. They stay available and stay honest -
              just not in the path of someone looking at their document. */}
          <Action
            label={showStages ? "Hide stages" : "Stages"}
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
            (doc.pages_excluded_with_clause_headings ?? 0) > 0
              ? "border-danger-500/40 bg-danger-500/10"
              : "border-warn-500/30 bg-warn-500/10",
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
              <p className="font-medium text-warn-500">
                {nf.format(doc.pages_excluded ?? 0)} page
                {(doc.pages_excluded ?? 0) === 1 ? "" : "s"} excluded from search
              </p>
              <p className="mt-1 text-slateish-300">
                {nf.format(doc.pages_excluded_characters ?? 0)} characters are not
                searchable. Front matter and contents pages are excluded on
                purpose; anything else is worth checking.
              </p>
            </>
          )}
          <button
            type="button"
            onClick={() => actions.onExcluded(doc)}
            className={[
              "mt-2 rounded border px-3 py-1 text-xs",
              (doc.pages_excluded_with_clause_headings ?? 0) > 0
                ? "border-danger-500/60 text-danger-500 hover:bg-danger-500/15"
                : "border-warn-500/60 text-warn-500 hover:bg-warn-500/15",
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
            className="mt-2 rounded border border-warn-500/60 px-3 py-1 text-xs text-warn-500 hover:bg-warn-500/15"
          >
            See what was excluded
          </button>
        </div>
      )}
    </li>
  );
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
        "rounded border px-2.5 py-1 text-xs transition-colors disabled:opacity-40",
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
