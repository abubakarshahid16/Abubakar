/**
 * The general review's results page (order 14, piece C; laid out as the owner's picture of 28 Nov 2026, round 1).
 *
 * Four tabs: Comments, To confirm, All points, How this review was made. The Comments tab carries ONE status box (the mark, the
 * verdict, what did not run, the team file) beside ONE sign-off box; the other tabs carry one short line, so their own content
 * starts at the top. On a signed review the sign-off warning is said ONCE, at the top of the page.
 *
 * Honest by construction: the mark "AI, to be checked" is on the header and on every row; the labels shown are the server's
 * `shown_label` (a Pass or Fail only where code compared a value, every other verdict says it is an AI opinion); the Download
 * button gives the team file and the server refuses it when the page, the database and the file rows differ, and this page says so.
 */
import { type ReactNode, useEffect, useState } from "react";

import { type GeneralLine, type GeneralReview, downloadGeneralSheet, generalReview } from "../../../api/generalReview";
import { CommentCards } from "./CommentCards";
import { SignBar } from "./SignBar";
import { HowReviewMade } from "./HowReviewMade";
import { MeasuredBadge } from "./MeasuredBadge";
import { Button, LinkButton, Notice, ShowMore, StatusChip } from "../../kit/Kit";
import { formatDay } from "../../../format/when";

const MARK_FALLBACK = "AI, to be checked";
/** Points drawn at first on the "All points" tab, and added per press of "Show more". */
const POINTS_PAGE = 50;
type Tab = "comments" | "confirm" | "all" | "how";

function PageLink({ page, onViewPage }: { page: number | null; onViewPage: (page: number) => void }) {
  if (page == null) return null; // a null page renders as nothing, never "page 0"
  return (
    <LinkButton tone="action" onClick={() => onViewPage(page)}>
      page {page}
    </LinkButton>
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

/** The verdict line at the top (E5): how many comments still need the engineer's decision, or that they are all decided, or the
 *  sign-off. With no sign-off state (an older review): the comment count, still marked as the AI's opinion. */
/** A stop reason the server sends as a code, in words (H's review of the owner's file, R3: "aim_identify: local_too_long (...)" was
 *  shown raw). A code not known here points to where the details are. */
export function stopSentence(reason: string): string {
  if (/too_long|window/i.test(reason)) return "The AI on this computer could not read this long document in one go. Run the review with Claude, or split the file.";
  // a reason already in words ("the spend limit was reached") is said as it is; only a code ("run_cap: ...") points to the details
  if (/\b[a-z]+_[a-z_]+\b/.test(reason)) return "The reason is under \u201cHow this review was made\u201d.";
  const words = reason.trim().replace(/\.$/, "");
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}.`;
}

export function verdict(review: GeneralReview, signoff: GeneralReview["signoff"] | null): string {
  const n = review.counts.comments;
  if (signoff?.state === "signed") return `${n} comment${n === 1 ? "" : "s"} decided.`; // "Signed off" is the box's own label just above
  // R1 (H's one-real-file pass, 27 Nov 2026): a review that stopped early, or that has no points, is never "ready to sign off"
  // (the server refuses its sign-off too: `aim_review_signoff.sign`)
  if (review.status === "stopped") return "This review stopped before it finished: there is nothing to sign off.";
  if (review.counts.points === 0) return "No points were reviewed: there is nothing to sign off.";
  if (signoff?.state === "changed") return "Changed since sign-off: sign it off again before the contractor copy.";
  if (signoff) {
    const todo = signoff.undecided_count;
    if (todo > 0) return `${todo} comment${todo === 1 ? "" : "s"} need${todo === 1 ? "s" : ""} your decision.`;
    return "All comments are decided: ready to sign off.";
  }
  return `${n} comment${n === 1 ? "" : "s"} to check (${review.counts.points} points reviewed).`;
}

/** True when this review can never be signed off as it is: it stopped early, or it has no points (R1). A review already signed keeps
 *  its sign-off bar (its state and the contractor copy). */
export function cannotSignOff(review: GeneralReview, signoff: GeneralReview["signoff"] | null): boolean {
  if (signoff?.state === "signed") return false;
  return review.status === "stopped" || review.counts.points === 0;
}

/** R2 (H's one-real-file pass, 27 Nov 2026): when the review on screen stopped, point to the paper's last COMPLETE review (newest
 *  first in the history), so an engineer is not left on an empty run while the real review sits as a History line. */
function LastCompleteReview({ review, onOpenRun }: { review: GeneralReview; onOpenRun?: (runId: string) => void }) {
  const [last, setLast] = useState<{ run_id: string; finished_at: string | null; points: number | null } | null>(null);
  useEffect(() => {
    let live = true;
    if (review.status !== "stopped") { setLast(null); return; }
    void generalReview.history(review.paper_document_id).then((r) => {
      if (!live || !r.ok) return;
      const done = r.data.runs.find((x) => x.run_id !== review.run_id && x.version === "general" && (x.status === "done" || x.status === "completed") && (x.points ?? 0) > 0);
      setLast(done ?? null);
    });
    return () => { live = false; };
  }, [review.paper_document_id, review.run_id, review.status]);
  if (review.status !== "stopped" || !last) return null;
  const day = formatDay(last.finished_at) || null; // the app's own "18 Nov 2026", never the browser's locale (H on #1981)
  return (
    <p data-testid="general-last-complete" className="text-sm text-slateish-100">
      The last complete review of this paper{day ? ` is from ${day}` : ""}{last.points != null ? ` (${last.points} points)` : ""}:{" "}
      {onOpenRun ? <LinkButton tone="action" onClick={() => onOpenRun(last.run_id)}>open it</LinkButton> : "it is listed under History"}.
    </p>
  );
}

export function GeneralResults({ review, howTab, onViewPage, onDownloaded, onReload, onOpenRun }: {
  review: GeneralReview; howTab: ReactNode; onViewPage: (page: number) => void; onDownloaded?: () => void;
  /** Read the whole review again (after "accept the rest": the cards then show the accepted comments). */
  onReload?: () => void | Promise<void>;
  /** Open another review of the same paper (the last complete one, when this one stopped). */
  onOpenRun?: (runId: string) => void;
}) {
  const mark = review.mark || MARK_FALLBACK;
  const [tab, setTab] = useState<Tab>("comments");
  const [pointsShown, setPointsShown] = useState(POINTS_PAGE);
  const [problem, setProblem] = useState<string | null>(null);
  const [askRough, setAskRough] = useState(false);
  const [signoff, setSignoff] = useState(review.signoff ?? null);
  // a rough draft from the local model that no engineer has signed: its file is given only after an explicit OK (lead-5, 27 Nov 2026)
  const roughUnsigned = review.engine?.local === true && signoff?.state !== "signed";
  useEffect(() => { setSignoff(review.signoff ?? null); }, [review.signoff]);
  const c = review.completeness;
  /** Read the sign-off state again (a decision or "accept the rest" changed what is undecided, or the sign-off itself went stale). */
  async function refreshSignoff() {
    const r = await generalReview.get(review.paper_document_id, review.run_id);
    if (r.ok && r.data.signoff) setSignoff(r.data.signoff);
  }
  const signed = signoff?.state === "signed";
  const stepsOff = (review.steps_not_applied ?? []).length;
  const partsOff = (review.pages_not_read ?? []).length;
  const tabs: { key: Tab; label: string }[] = [
    { key: "comments", label: `Comments (${review.counts.comments})` },
    ...(review.counts.confirmations != null ? [{ key: "confirm" as const, label: `To confirm (${review.counts.confirmations})` }] : []),
    { key: "all", label: `All points (${review.counts.points})` },
    { key: "how", label: "How this review was made" },
  ];
  const plainRow = (l: GeneralLine) => <Row key={`p-${l.n}-${l.item_id}`} line={l} mark={mark} onViewPage={onViewPage} />;

  async function download(roughOk = false) {
    setProblem(null);
    if (roughUnsigned && !roughOk) {
      setAskRough(true);
      return;
    }
    setAskRough(false);
    const bad = await downloadGeneralSheet(review.paper_document_id, review.run_id, "team", roughOk);
    if (bad) setProblem(bad);
    else onDownloaded?.();
  }

  return (
    <div data-testid="general-results" className="space-y-4">
      {review.stop_words && (
        <div role="alert" data-testid="general-account-stop" className="rounded-[var(--radius-md)] border border-danger-500 p-3 text-sm text-danger-500">
          <strong>This review did not finish.</strong> {review.stop_words}
        </div>
      )}
      {/* SAID ONCE, at the top (owner, 28 Nov 2026): on a signed review a click on a decision button changes a signed sheet. Each
          button then carries only the short mark (*). */}
      {signed && (
        <div data-testid="general-signed-warning">
          <Notice tone="warn" title="This review is signed off. A click on Accept, Edit or Reject changes a signed sheet.">
            The sign-off is undone at once, the contractor copy is held back, and you sign again. The buttons marked * do this.
            <span className="mt-1 block">Accept: the comment goes to the contractor as written. Edit: it goes with your wording. Reject: it is left out, and you give a one-line reason.</span>
          </Notice>
        </div>
      )}
      {/* ANSWER FIRST (owner's picture, 28 Nov 2026): ONE status box and ONE sign-off box, on the Comments tab only. The other tabs
          carry one short line, so their own content starts at the top. */}
      {tab === "comments" ? (
        <div className="grid gap-3 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <div role="note" data-testid="general-mark" className="kit-card space-y-2">
            <StatusChip word={signed ? "Signed off" : mark} />
            <p data-testid="general-verdict" className="text-lg font-semibold text-slateish-100">{verdict(review, signoff)}</p>
            <p className="text-sm text-slateish-300">
              {signed ? "The contractor copy is in the sign-off box. This page is still the team's full list."
                : "This is the AI's opinion, for the team: nothing here is signed off or ready for the contractor."}
            </p>
            {stepsOff > 0 && (
              <p data-testid="general-steps-pointer" className="text-sm text-pill-review-fg">
                {stepsOff} checking step{stepsOff === 1 ? "" : "s"} did not run:{" "}
                <LinkButton tone="inherit" onClick={() => setTab("how")}>see How this review was made</LinkButton>.
              </p>
            )}
            {partsOff > 0 && (
              <p data-testid="general-pages-pointer" className="text-sm text-pill-review-fg">
                {partsOff} part{partsOff === 1 ? "" : "s"} of this paper {partsOff === 1 ? "was" : "were"} not read:{" "}
                <LinkButton tone="inherit" onClick={() => setTab("how")}>see How this review was made</LinkButton>.
              </p>
            )}
            {/* three counts of 0: there is no file to give out, so no button that can only be refused (H on #1981) */}
            {!review.completeness?.nothing_to_compare && (
              <div className="flex flex-wrap items-center gap-3">
                <Button variant="secondary" size="sm" onClick={() => void download()} data-testid="general-download">
                  Download the file (team copy)
                </Button>
                {!signed && <span className="text-xs text-slateish-300">The contractor copy comes after sign-off.</span>}
              </div>
            )}
            {askRough && (
              <div data-testid="general-rough-confirm">
                <Notice tone="warn">
                  This review is a rough draft by the AI on this computer, not scored as reliable. Check every comment before you use the file.
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button variant="secondary" size="sm" onClick={() => void download(true)} data-testid="general-rough-ok">I will check every comment: download</Button>
                    <LinkButton tone="action" onClick={() => setAskRough(false)}>Cancel</LinkButton>
                  </div>
                </Notice>
              </div>
            )}
            {problem && <p role="alert" data-testid="general-download-problem" className="text-sm text-danger-500">{problem}</p>}
          </div>
          {signoff && !cannotSignOff(review, signoff) && <SignBar review={review} signoff={signoff} onStatus={setSignoff} onChanged={() => { if (onReload) void onReload(); else void refreshSignoff(); }} />}
        </div>
      ) : (
        <p data-testid="general-mark-short" className="flex flex-wrap items-center gap-2 text-sm text-slateish-200">
          <StatusChip word={signed ? "Signed off" : mark} />
          <span>{verdict(review, signoff)}</span>
        </p>
      )}
      {/* C's notes on #1981: the way to the last complete review comes FIRST, straight under the verdict */}
      <LastCompleteReview review={review} onOpenRun={onOpenRun} />
      {tab === "comments" && <MeasuredBadge measured={review.measured} />}{/* the kind's real score stays on screen (standing order: "below target" shown) */}
      {review.status === "stopped" && (
        <p role="alert" data-testid="general-stopped" className="text-sm text-danger-500">
          This review stopped early.{review.stop_reason && !review.stop_words ? ` ${stopSentence(review.stop_reason)}` : ""}
          {review.counts.points > 0 ? " The points below are the ones it reached." : ""}
        </p>
      )}
      {!c.ok && (c.nothing_to_compare ? (
        // one fact, one red: the stop line above is the alarm; three counts of 0 are a quiet note, not a second red box
        <div data-testid="general-incomplete"><Notice tone="quiet">{c.sentence}</Notice></div>
      ) : (
        <div role="alert" data-testid="general-incomplete" className="rounded-[var(--radius-md)] border border-danger-500 p-3 text-sm text-danger-500">
          <p>{c.sentence ?? `The file is not complete: the page has ${c.page} points, the database ${c.database}, the file ${c.file_rows}.`}</p>
        </div>
      ))}

      <div role="tablist" aria-label="Review" className="flex gap-1 overflow-x-auto border-b border-ink-600">
        {tabs.map(({ key, label }) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
            className={`whitespace-nowrap px-4 py-2 text-sm ${tab === key ? "border-b-2 border-signal-400 text-slateish-100" : "text-slateish-300 hover:text-slateish-100"}`}>
            {label}
          </button>
        ))}
      </div>

      {/* the comments and the points to confirm stay in the page while another tab is open, so a decision just made is still shown */}
      <div className="space-y-3" hidden={tab !== "comments"}>
        <CommentCards review={review} mark={mark} signed={signed} onDecided={() => void refreshSignoff()} onViewPage={onViewPage} renderPlain={plainRow} />
        {(review.rejected_before ?? []).length > 0 && (
          <section data-testid="general-rejected-before" aria-label="Rejected before" className="space-y-1 rounded-[var(--radius-sm)] border border-ink-600 p-3">
            <h3 className="text-sm font-semibold text-slateish-200">Rejected before ({review.rejected_before!.length}), team only: not raised again, never sent</h3>
            <ul className="space-y-1 text-sm text-slateish-300">
              {review.rejected_before!.map((c) => (
                <li key={`rb-${c.n}`}><span className="text-slateish-100">{c.title ?? c.field}</span>: {c.rejected_before.note}</li>
              ))}
            </ul>
          </section>
        )}
      </div>
      {review.counts.confirmations != null && (
        <div hidden={tab !== "confirm"}>
          <CommentCards part="confirmations" review={review} mark={mark} signed={signed} onDecided={() => void refreshSignoff()} onViewPage={onViewPage} renderPlain={plainRow} />
        </div>
      )}

      {tab === "all" && (
        <div className="space-y-3" data-testid="general-all">
          {review.points.length === 0 && <p className="text-sm text-slateish-300">This review has no points.</p>}
          <ul className="space-y-2">{review.points.slice(0, pointsShown).map((l) => <Row key={`${l.n}-${l.item_id}`} line={l} mark={mark} onViewPage={onViewPage} />)}</ul>
          <ShowMore testId="points-more" shown={Math.min(pointsShown, review.points.length)} total={review.points.length} step={POINTS_PAGE} onMore={() => setPointsShown((n) => n + POINTS_PAGE)} />
        </div>
      )}

      {tab === "how" && (
        <div data-testid="general-how" className="space-y-3 text-sm text-slateish-200">
          <HowReviewMade review={review} onOpenTab={(t) => setTab(t)} />
          {howTab}
        </div>
      )}
    </div>
  );
}
