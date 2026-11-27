/**
 * The redesigned review page (owner, 12 Nov 2026; SPEC.md), drawn only while `REVIEW_PAGE_V2_ENABLED` is on. Top to bottom: the header
 * with the kind and the ONE engine choice and Review button; the engine line; the review code box; four tiles; rule book chips; the
 * rule books not held; three tabs (Points, CRS sheet, How it was reviewed); the list of points; Add a point; the bottom row.
 *
 * The CRS sheet and How it was reviewed tabs hold today's screens, handed in by the workspace (it owns their state).
 */
import { type ReactNode, useMemo, useState } from "react";

import type { ReviewRunSummary } from "../../../types/api";
import type { DocumentRecord } from "../../../types/api";
import { PageImageViewer } from "../../PageImageViewer";
import { GeneralHistory } from "../general/GeneralHistory";
import { GeneralResults } from "../general/GeneralResults";
import { latestGeneral, useGeneralReview } from "../general/useGeneralReview";
import { AddPoint } from "./AddPoint";
import { BottomRow } from "./BottomRow";
import { OlderFiles } from "./OlderFiles";
import { CodeBox } from "./CodeBox";
import { FoundDuringReview } from "../panels/FoundDuringReview";
import { EngineBar } from "./EngineBar";
import { KindLine } from "./KindLine";
import { NotApplicableSection } from "./NotApplicableSection";
import { PointsList } from "./PointsList";
import { BookChips, NO_BOOK, NotHeldLine, type TileKey, Tiles } from "./Tiles";
import { usePoints } from "./usePoints";
import { Button, LinkButton } from "../../kit/Kit";

export type V2Tab = "points" | "sheet" | "how";
const TAB_LABEL: Record<V2Tab, string> = { points: "Points", sheet: "CRS sheet", how: "How it was reviewed" };

export function ReviewPageV2({ run, submittal, isAdmin, onBack, onOpenRun, sheetTab, howTab, onSign, signBlockers, signed, onCodeRecorded }: {
  run: ReviewRunSummary; submittal: DocumentRecord | null; isAdmin: boolean | undefined; onBack: () => void; onOpenRun: (runId: string) => void;
  sheetTab: ReactNode; howTab: ReactNode; onSign: () => void; signBlockers: string[]; signed: boolean; onCodeRecorded: () => void;
}) {
  const documentId = run.submittal_document_id ?? null;
  // Order 14: when the paper's latest finished review is a general one, the general results are drawn instead of the old sections.
  // the general review OPENED (a general run's own id), so the page is the review its row and Open named; an earlier run: the latest
  const { general, method, reload: reloadGeneral } = useGeneralReview(documentId, run.method === "general" ? run.review_run_id : null);
  const latest = latestGeneral(general);
  const generalLatest = latest !== null;
  // the older sections wait until it is known which review is the latest, so one page never flashes into the other
  const drawOld = !generalLatest && general.state !== "loading";
  const pts = usePoints(generalLatest ? null : documentId);
  const [tab, setTab] = useState<V2Tab>("points");
  const [again, setAgain] = useState(false); // the engine choice and plan of a new review, opened by "Review this paper again"
  const [tile, setTile] = useState<TileKey | null>(null);
  const [book, setBook] = useState<string | null>(null);
  const [viewing, setViewing] = useState<{ page: number } | null>(null);
  const listing = pts.listing.state === "ok" ? pts.listing.data : null;

  // owner on PR #1872: the lines the AI thinks do not apply are their own section, never in the main list
  const toConfirm = useMemo(() => (listing?.points ?? []).filter((p) => p.tile === "na_to_confirm"), [listing]);
  const shown = useMemo(() => (listing?.points ?? []).filter((p) => p.tile !== "na_to_confirm" && (tile ? p.tile === tile : true) && (book === null ? true : book === NO_BOOK ? p.no_book === true : (p.books ?? []).some((b) => b.id === book) || (!p.books && p.rule_book === book))), [listing, tile, book]);
  const undecided = listing ? listing.of - listing.decided : 0;

  return (
    <section data-testid="review-page-v2" className="mx-auto w-full max-w-7xl space-y-4" aria-labelledby="v2-title">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-[16rem] flex-1 space-y-1">
          <LinkButton tone="action" size="sm" onClick={onBack}>← Reviews</LinkButton>
          <h1 id="v2-title" title={run.submittal_filename ?? undefined} className="truncate text-2xl font-semibold text-slateish-100">{run.submittal_filename ?? "Review"}</h1>
          <KindLine documentId={documentId} pages={submittal?.page_count} isAdmin={isAdmin} aiEquipment={latest?.identity?.equipment_type ?? null} />
        </div>
        <div className="min-w-[18rem]">
          {/* A finished review's page is about THAT review: the engine choice and the plan of a NEW review wait behind "Review again" (a
              plan shown here read like the plan of the run on screen, and its "Checking..." could hang under the button). */}
          {general.state === "loading" ? null : generalLatest && !again ? (
            isAdmin !== false ? (
              <Button variant="secondary" size="sm" data-testid="review-again" onClick={() => setAgain(true)}>
                Review this paper again
              </Button>
            ) : null
          ) : (
            <EngineBar documentId={documentId} isAdmin={isAdmin} onStarted={onOpenRun} />
          )}
        </div>
      </header>

      {general.state === "loading" && <p className="text-slateish-300">Reading the review…</p>}
      {latest && run.newer_note && (
        // the review opened is the file's face (signed, or made on Claude); a newer one is never hidden: it is named, and listed under
        // "How this review was made"
        <p data-testid="v2-newer-note" className="text-sm text-pill-review-fg">{run.newer_note}. It is listed under &quot;How this review was made&quot;.</p>
      )}
      {latest && (
        <GeneralResults review={latest} onViewPage={(page) => setViewing({ page })} onReload={reloadGeneral}
          howTab={<><GeneralHistory documentId={latest.paper_document_id} />{howTab}</>} />
      )}
      {drawOld && (general.state === "ok" || method === "general") && (
        <h2 data-testid="earlier-version" className="text-lg font-semibold text-slateish-200">Earlier version</h2>
      )}
      {drawOld && pts.listing.state === "loading" && <p className="text-slateish-300">Reading the points…</p>}
      {drawOld && pts.listing.state === "error" && <p role="alert" className="text-danger-500">{pts.listing.message}</p>}
      {drawOld && listing && (
        <>
          <FoundDuringReview count={listing.found_during_review ?? 0} />
          <CodeBox listing={listing} onRecorded={() => { void pts.reload(); onCodeRecorded(); }} />
          {listing.completeness && !listing.completeness.ok && (
            <div role="alert" data-testid="v2-incomplete" className="rounded-[var(--radius-md)] border border-danger-500 p-3 text-sm text-danger-500">
              <p>
                This review's file is not complete, so the CRS downloads and signing are refused: the page has {listing.completeness.page} points, the database
                {" "}{listing.completeness.database} lines, the team file {listing.completeness.team_rows} rows.
              </p>
              {listing.completeness.missing.length > 0 && (
                <ul className="mt-1 list-disc pl-5">
                  {listing.completeness.missing.slice(0, 10).map((m) => <li key={m}>{m}</li>)}
                  {listing.completeness.missing.length > 10 && <li>and {listing.completeness.missing.length - 10} more</li>}
                </ul>
              )}
            </div>
          )}
          {listing.comment_count != null && (
            <p data-testid="v2-comment-count" className="text-xs text-slateish-400">
              {listing.of} points reviewed, as {listing.comment_count} comments in the CRS file (one comment per field; every point stays on the sheet Evidence).
            </p>
          )}
          <Tiles counts={listing.counts} selected={tile} onSelect={setTile} />
          <BookChips counts={listing.counts} selected={book} onSelect={setBook} />
          <NotHeldLine counts={listing.counts} onSeeAll={() => setTab("how")} />
        </>
      )}

      {drawOld && <div role="tablist" aria-label="Review" className="flex gap-1 border-b border-ink-600">
        {(Object.keys(TAB_LABEL) as V2Tab[]).map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm ${tab === t ? "border-b-2 border-signal-400 text-slateish-100" : "text-slateish-300 hover:text-slateish-100"}`}>
            {t === "points" && listing ? `Points (${listing.of})` : TAB_LABEL[t]}
          </button>
        ))}
      </div>}

      {drawOld && tab === "points" && listing && (
        <div className="space-y-3">
          {pts.problem && <p role="alert" className="text-sm text-danger-500">{pts.problem}</p>}
          <NotApplicableSection points={toConfirm} counts={listing.counts.not_applicable_to_confirm} confirm={pts.confirmNa} undo={pts.undoNa} busy={pts.busy} />
          <PointsList points={shown} decide={pts.decide} keepAll={pts.keepAll} busy={pts.busy}
            onViewPage={(_d, page) => setViewing({ page })} />
          <AddPoint onAdd={pts.add} busy={pts.busy} />
        </div>
      )}
      {drawOld && tab === "sheet" && <div data-testid="v2-sheet-tab">{sheetTab}</div>}
      {drawOld && tab === "how" && (
        <div data-testid="v2-how-tab">
          {howTab}
          {listing && <OlderFiles ruleCheckRun={listing.runs.rule_check} aiRun={listing.runs.ai_review} {...{ documentId }} />}
        </div>
      )}

      {drawOld && listing && (
        <BottomRow documentId={documentId} undecided={undecided}
          codeRecorded={listing.final_code != null} blockers={signBlockers} signed={signed} onSign={onSign} />
      )}
      {viewing && submittal && <PageImageViewer doc={submittal} initialPage={viewing.page} onClose={() => setViewing(null)} />}
    </section>
  );
}
