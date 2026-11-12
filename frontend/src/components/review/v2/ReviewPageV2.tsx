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
import { AddPoint } from "./AddPoint";
import { BottomRow } from "./BottomRow";
import { CodeBox } from "./CodeBox";
import { EngineBar } from "./EngineBar";
import { KindLine } from "./KindLine";
import { PointsList } from "./PointsList";
import { BookChips, NO_BOOK, NotHeldLine, type TileKey, Tiles } from "./Tiles";
import { usePoints } from "./usePoints";

export type V2Tab = "points" | "sheet" | "how";
const TAB_LABEL: Record<V2Tab, string> = { points: "Points", sheet: "CRS sheet", how: "How it was reviewed" };

export function ReviewPageV2({ run, submittal, isAdmin, onBack, onOpenRun, sheetTab, howTab, onSign, signBlockers, signed, onCodeRecorded }: {
  run: ReviewRunSummary; submittal: DocumentRecord | null; isAdmin: boolean | undefined; onBack: () => void; onOpenRun: (runId: string) => void;
  sheetTab: ReactNode; howTab: ReactNode; onSign: () => void; signBlockers: string[]; signed: boolean; onCodeRecorded: () => void;
}) {
  const documentId = run.submittal_document_id ?? null;
  const pts = usePoints(documentId);
  const [tab, setTab] = useState<V2Tab>("points");
  const [tile, setTile] = useState<TileKey | null>(null);
  const [book, setBook] = useState<string | null>(null);
  const [viewing, setViewing] = useState<{ page: number } | null>(null);
  const listing = pts.listing.state === "ok" ? pts.listing.data : null;

  const shown = useMemo(() => (listing?.points ?? []).filter((p) => (tile ? p.tile === tile : true) && (book === null ? true : book === NO_BOOK ? p.no_book === true : (p.books ?? []).some((b) => b.id === book) || (!p.books && p.rule_book === book))), [listing, tile, book]);
  const undecided = listing ? listing.of - listing.decided : 0;

  return (
    <section data-testid="review-page-v2" className="mx-auto w-full max-w-7xl space-y-4" aria-labelledby="v2-title">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-[16rem] flex-1 space-y-1">
          <button type="button" onClick={onBack} className="text-sm text-signal-300 underline-offset-2 hover:underline">← Reviews</button>
          <h1 id="v2-title" className="truncate text-2xl font-semibold text-slateish-100">{run.submittal_filename ?? "Review"}</h1>
          <KindLine documentId={documentId} pages={submittal?.page_count} isAdmin={isAdmin} />
        </div>
        <div className="min-w-[18rem]"><EngineBar documentId={documentId} isAdmin={isAdmin} onStarted={onOpenRun} /></div>
      </header>

      {pts.listing.state === "loading" && <p className="text-slateish-300">Reading the points…</p>}
      {pts.listing.state === "error" && <p role="alert" className="text-danger-500">{pts.listing.message}</p>}
      {listing && (
        <>
          <CodeBox listing={listing} onRecorded={() => { void pts.reload(); onCodeRecorded(); }} />
          <Tiles counts={listing.counts} selected={tile} onSelect={setTile} />
          <BookChips counts={listing.counts} selected={book} onSelect={setBook} />
          <NotHeldLine counts={listing.counts} onSeeAll={() => setTab("how")} />
        </>
      )}

      <div role="tablist" aria-label="Review" className="flex gap-1 border-b border-ink-600">
        {(Object.keys(TAB_LABEL) as V2Tab[]).map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm ${tab === t ? "border-b-2 border-signal-400 text-slateish-100" : "text-slateish-300 hover:text-slateish-100"}`}>
            {t === "points" && listing ? `Points (${listing.of})` : TAB_LABEL[t]}
          </button>
        ))}
      </div>

      {tab === "points" && listing && (
        <div className="space-y-3">
          {pts.problem && <p role="alert" className="text-sm text-danger-500">{pts.problem}</p>}
          <PointsList points={shown} decide={pts.decide} keepAll={pts.keepAll} busy={pts.busy}
            onViewPage={(_d, page) => setViewing({ page })} />
          <AddPoint onAdd={pts.add} busy={pts.busy} />
        </div>
      )}
      {tab === "sheet" && <div data-testid="v2-sheet-tab">{sheetTab}</div>}
      {tab === "how" && <div data-testid="v2-how-tab">{howTab}</div>}

      {listing && (
        <BottomRow ruleCheckRun={listing.runs.rule_check} aiRun={listing.runs.ai_review} undecided={undecided}
          codeRecorded={listing.final_code != null} blockers={signBlockers} signed={signed} onSign={onSign}
          contractorWords={listing.contractor_copy?.words ?? null} />
      )}
      {viewing && submittal && <PageImageViewer doc={submittal} initialPage={viewing.page} onClose={() => setViewing(null)} />}
    </section>
  );
}
