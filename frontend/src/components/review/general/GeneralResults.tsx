/**
 * The general review's results page (order 14, piece C): what the ONE Review button's new method produced for a paper.
 *
 * Honest by construction: the mark "AI, to be checked" is on the header and on every row; the labels shown are the server's
 * `shown_label` (a Pass or Fail only where code compared a value, every other verdict says it is an AI opinion); there is NO
 * contractor button, NO sign row and NO review code here (no sign-off is connected to the general review); the one Download button
 * gives the team file and the server refuses it when the page, the database and the file rows differ, and this page says so.
 */
import { type ReactNode, useState } from "react";

import { type GeneralLine, type GeneralReview, downloadGeneralSheet } from "../../../api/generalReview";

const MARK_FALLBACK = "AI, to be checked";

function PageLink({ page, onViewPage }: { page: number | null; onViewPage: (page: number) => void }) {
  if (page == null) return null; // a null page renders as nothing, never "page 0"
  return (
    <button type="button" onClick={() => onViewPage(page)} className="text-signal-300 underline-offset-2 hover:underline">
      page {page}
    </button>
  );
}

function Row({ line, mark, onViewPage }: { line: GeneralLine; mark: string; onViewPage: (page: number) => void }) {
  return (
    <li data-testid="general-row" className="space-y-1 rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-slateish-100">{line.field || line.item_id}</span>
        <span className="rounded-[var(--radius-sm)] border border-ink-500 px-2 py-0.5 text-xs text-slateish-200">{line.shown_label}</span>
        <span className="text-xs text-slateish-400">{mark}</span>
        <span className="ml-auto text-xs"><PageLink page={line.page} onViewPage={onViewPage} /></span>
      </div>
      {line.comment && <p className="text-slateish-200">{line.comment}</p>}
      {line.quote && (
        <blockquote className="border-l-2 border-ink-500 pl-3 text-xs text-slateish-300">
          {line.quote}
          {line.quote_unverified && <span className="ml-2 text-slateish-400">(code could not find this quote on the page)</span>}
        </blockquote>
      )}
      {(line.standard || line.clause) && (
        <p className="text-xs text-slateish-400">{[line.standard, line.clause].filter(Boolean).join(", clause ")}</p>
      )}
    </li>
  );
}

export function GeneralResults({ review, howTab, onViewPage, onDownloaded }: {
  review: GeneralReview; howTab: ReactNode; onViewPage: (page: number) => void; onDownloaded?: () => void;
}) {
  const mark = review.mark || MARK_FALLBACK;
  const [tab, setTab] = useState<"comments" | "how">("comments");
  const [showAll, setShowAll] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const c = review.completeness;
  const lines = showAll ? review.points : review.comments;

  async function download() {
    setProblem(null);
    const bad = await downloadGeneralSheet(review.paper_document_id, review.run_id);
    if (bad) setProblem(bad);
    else onDownloaded?.();
  }

  return (
    <div data-testid="general-results" className="space-y-4">
      <div role="note" data-testid="general-mark" className="rounded-[var(--radius-md)] border border-signal-400 p-3 text-sm text-slateish-100">
        <strong>{mark}</strong>
        <span className="ml-2 text-slateish-300">General review. This is the AI's opinion, for the team: nothing here is signed off or ready for the contractor.</span>
      </div>

      {review.status === "stopped" && (
        <p role="alert" data-testid="general-stopped" className="text-sm text-danger-500">
          This review stopped early{review.stop_reason ? `: ${review.stop_reason}` : ""}. The points below are the ones it reached.
        </p>
      )}
      {!c.ok && (
        <div role="alert" data-testid="general-incomplete" className="rounded-[var(--radius-md)] border border-danger-500 p-3 text-sm text-danger-500">
          <p>{c.sentence ?? `The file is not complete: the page has ${c.page} points, the database ${c.database}, the file ${c.file_rows}.`}</p>
        </div>
      )}

      <p data-testid="general-counts" className="text-sm text-slateish-200">
        {review.counts.points} points reviewed, as {review.counts.comments} comments ({review.counts.boundary}).
        {Object.entries(review.counts.by_shown_label ?? {}).filter(([k]) => k).map(([k, n]) => (
          <span key={k} className="ml-2 text-xs text-slateish-400">{k}: {n}</span>
        ))}
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={() => void download()} data-testid="general-download"
          className="rounded-[var(--radius-sm)] border border-ink-500 px-3 py-1.5 text-sm text-slateish-100 hover:bg-ink-700">
          Download the file (team copy)
        </button>
        {review.cost.usd != null && <span data-testid="general-cost" className="text-xs text-slateish-400">Cost of this review: USD {review.cost.usd.toFixed(2)}</span>}
      </div>
      {problem && <p role="alert" data-testid="general-download-problem" className="text-sm text-danger-500">{problem}</p>}

      <div role="tablist" aria-label="General review" className="flex gap-1 border-b border-ink-600">
        {([["comments", `Comments (${review.counts.comments})`], ["how", "How it was reviewed"]] as const).map(([t, label]) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm ${tab === t ? "border-b-2 border-signal-400 text-slateish-100" : "text-slateish-300 hover:text-slateish-100"}`}>
            {label}
          </button>
        ))}
      </div>

      {tab === "comments" && (
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm text-slateish-300">
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} data-testid="general-all-toggle" />
            All points ({review.counts.points})
          </label>
          {lines.length === 0 && <p className="text-sm text-slateish-300">{showAll ? "This review has no points." : "This review has no comments."}</p>}
          <ul className="space-y-2">{lines.map((l) => <Row key={`${l.n}-${l.item_id}`} line={l} mark={mark} onViewPage={onViewPage} />)}</ul>
        </div>
      )}

      {tab === "how" && (
        <div data-testid="general-how" className="space-y-3 text-sm text-slateish-200">
          <section aria-label="Rule books used" className="space-y-1">
            <h3 className="font-semibold text-slateish-100">Rule books used ({review.books.length}{review.books_not_readable ? `, and ${review.books_not_readable} you may not open` : ""})</h3>
            {review.books.length === 0 ? <p className="text-slateish-400">none</p> : (
              <ul className="list-disc pl-5">{review.books.map((b) => <li key={b.id}>{b.title}{b.why ? <span className="text-slateish-400"> ({b.why})</span> : null}</li>)}</ul>
            )}
          </section>
          <section aria-label="Rule books not held" className="space-y-1">
            <h3 className="font-semibold text-slateish-100">Rule books not held ({review.not_held.length})</h3>
            {review.not_held.length === 0 ? <p className="text-slateish-400">none</p> : (
              <ul className="list-disc pl-5">{review.not_held.map((b) => <li key={b.name}>{b.name}{b.why ? <span className="text-slateish-400"> ({b.why})</span> : null}</li>)}</ul>
            )}
          </section>
          {review.unlisted_books.sentence && <p data-testid="general-unlisted" className="text-slateish-200">{review.unlisted_books.sentence}</p>}
          {review.checklist.key && (
            <p className="text-xs text-slateish-400">
              Checklist: {review.checklist.items ?? "?"} items{review.checklist.reused != null ? (review.checklist.reused ? ", reused from an earlier review" : ", built for this review") : ""}
              {review.checklist.built_from ? `; built from: ${review.checklist.built_from}` : ""}.
            </p>
          )}
          {howTab}
        </div>
      )}
    </div>
  );
}
