/**
 * The general review's results page (order 14, piece C): what the ONE Review button's new method produced for a paper.
 *
 * Honest by construction: the mark "AI, to be checked" is on the header and on every row; the labels shown are the server's
 * `shown_label` (a Pass or Fail only where code compared a value, every other verdict says it is an AI opinion); there is NO
 * contractor button, NO sign row and NO review code here (no sign-off is connected to the general review); the one Download button
 * gives the team file and the server refuses it when the page, the database and the file rows differ, and this page says so.
 */
import { type ReactNode, useEffect, useState } from "react";

import { type GeneralLine, type GeneralReview, downloadGeneralSheet, generalReview } from "../../../api/generalReview";
import { CommentCards } from "./CommentCards";
import { SignBar } from "./SignBar";
import { HowReviewMade } from "./HowReviewMade";
import { MeasuredBadge } from "./MeasuredBadge";

const MARK_FALLBACK = "AI, to be checked";
/** The shown labels in plain words for the header's counts (a label not listed is shown as written, in lower case). */
const SHOWN_WORDS: Record<string, string> = {
  "Question": "questions", "AI opinion": "other AI opinions", "AI opinion: met": "met (the AI's view)",
  "AI opinion: not met": "not met (the AI's view)",
  "AI opinion: does not apply": "do not apply (the AI's view)", "Fail, compared by code": "failed, compared by code", "Pass, compared by code": "passed, compared by code",
};

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

export function GeneralResults({ review, howTab, onViewPage, onDownloaded, onReload }: {
  review: GeneralReview; howTab: ReactNode; onViewPage: (page: number) => void; onDownloaded?: () => void;
  /** Read the whole review again (after "accept the rest": the cards then show the accepted comments). */
  onReload?: () => void | Promise<void>;
}) {
  const mark = review.mark || MARK_FALLBACK;
  const [tab, setTab] = useState<"comments" | "how">("comments");
  const [showAll, setShowAll] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [signoff, setSignoff] = useState(review.signoff ?? null);
  useEffect(() => { setSignoff(review.signoff ?? null); }, [review.signoff]);
  const c = review.completeness;
  /** Read the sign-off state again (a decision or "accept the rest" changed what is undecided, or the sign-off itself went stale). */
  async function refreshSignoff() {
    const r = await generalReview.get(review.paper_document_id, review.run_id);
    if (r.ok && r.data.signoff) setSignoff(r.data.signoff);
  }
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
        {signoff?.state === "signed" && signoff.signed ? (
          <>
            <strong>Signed off</strong>
            <span className="ml-2 text-slateish-300">General review, signed off by {signoff.signed.by}. The contractor copy is below; this page is still the team's full list.</span>
          </>
        ) : (
          <>
            <strong>{mark}</strong>
            <span className="ml-2 text-slateish-300">General review. This is the AI's opinion, for the team: nothing here is signed off or ready for the contractor.</span>
          </>
        )}
      </div>
      <MeasuredBadge measured={review.measured} />

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

      {(review.steps_not_applied ?? []).length > 0 && (
        <div role="note" data-testid="general-steps-not-applied" className="space-y-1 rounded-[var(--radius-md)] border border-warn-500 p-3 text-sm text-slateish-100">
          <strong>A checking step did not run on this sheet.</strong>
          <ul className="list-disc pl-5 text-slateish-200">
            {(review.steps_not_applied ?? []).map((x) => <li key={x.step}>{x.sentence}</li>)}
          </ul>
        </div>
      )}

      {(review.pages_not_read ?? []).length > 0 && (
        <div role="note" data-testid="general-pages-not-read" className="space-y-1 rounded-[var(--radius-md)] border border-warn-500 p-3 text-sm text-slateish-100">
          <strong>{(review.pages_not_read ?? []).length} part{(review.pages_not_read ?? []).length === 1 ? "" : "s"} of this paper were not read.</strong>
          <p className="text-slateish-200">Nothing below says anything about them: no text and no picture reading came back, or it has not run yet.</p>
          <ul className="list-disc pl-5 text-slateish-200">
            {(review.pages_not_read ?? []).map((x) => <li key={x.where}>{x.sentence}</li>)}
          </ul>
        </div>
      )}

      <p data-testid="general-counts" className="text-sm text-slateish-200">
        {review.counts.points} points reviewed, {review.counts.comments} comments sent
        {review.counts.confirmations != null ? `, ${review.counts.confirmations} confirmations not sent` : ""} ({review.counts.boundary}).
        {Object.entries(review.counts.by_shown_label ?? {}).filter(([k]) => k).map(([k, n]) => (
          <span key={k} className="ml-2 text-xs text-slateish-400">{n} {SHOWN_WORDS[k] ?? k.toLowerCase()}</span>
        ))}
        {" "}{review.counts.decided_by_code?.sentence}
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={() => void download()} data-testid="general-download"
          className="rounded-[var(--radius-sm)] border border-ink-500 px-3 py-1.5 text-sm text-slateish-100 hover:bg-ink-700">
          Download the file (team copy)
        </button>
        {review.cost.usd != null && <span data-testid="general-cost" className="text-xs text-slateish-400">Cost of this review: USD {review.cost.usd.toFixed(2)}</span>}
      </div>
      {problem && <p role="alert" data-testid="general-download-problem" className="text-sm text-danger-500">{problem}</p>}

      {signoff && <SignBar review={review} signoff={signoff} onStatus={setSignoff} onChanged={() => { if (onReload) void onReload(); else void refreshSignoff(); }} />}

      <div role="tablist" aria-label="General review" className="flex gap-1 border-b border-ink-600">
        {([["comments", `Comments (${review.counts.comments})`], ["how", "How this review was made"]] as const).map(([t, label]) => (
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
          {showAll ? (
            <>
              {lines.length === 0 && <p className="text-sm text-slateish-300">This review has no points.</p>}
              <ul className="space-y-2">{lines.map((l) => <Row key={`${l.n}-${l.item_id}`} line={l} mark={mark} onViewPage={onViewPage} />)}</ul>
            </>
          ) : (
            <CommentCards review={review} mark={mark} onDecided={() => void refreshSignoff()} onViewPage={onViewPage}
              renderPlain={(l) => <Row key={`p-${l.n}-${l.item_id}`} line={l} mark={mark} onViewPage={onViewPage} />} />
          )}
        </div>
      )}

      {tab === "how" && (
        <div data-testid="general-how" className="space-y-3 text-sm text-slateish-200">
          <HowReviewMade review={review} />
          {howTab}
        </div>
      )}
    </div>
  );
}
