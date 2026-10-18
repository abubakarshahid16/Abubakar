/**
 * The Sheet's header (order 95 piece 2, spec 1.2): document, equipment type,
 * revision, ONE headline line, the proposed code with its reason, and the
 * sheet actions.
 */
import type { DocumentRecord, ReviewRunSummary } from "../../../types/api";
import { orNothing } from "../reviewFormat";
import { type CrsRow, crsHeadline } from "./crsRows";
import type { TierCounts } from "./tiers";

export interface CrsHeaderProps {
  run: ReviewRunSummary;
  submittal: DocumentRecord | null;
  counts: TierCounts;
  /** Tier C rows the engineer has not opened yet (Sign waits for them). */
  unopened: CrsRow[];
  /** How many Comment rows "Accept all remaining" would keep right now. */
  remaining: number;
  /** How many Keep / Edit wording / Remove decisions are held on this
   *  screen only (not yet in the exported file). */
  localDecisions: number;
  acceptAll: { confirming: boolean; onAsk: () => void; onConfirm: () => void; onCancel: () => void; canUndo: boolean; onUndo: () => void; kept: number | null };
  sign: { busy: boolean; onSign: () => void; onWorkingCopy: () => void; message: string | null; error: string | null };
  onBack: () => void;
  onOpenCards: () => void;
  onOpenReviewed?: () => void;
}

export function CrsHeader({ run, submittal, counts, unopened, remaining, localDecisions, acceptAll, sign, onBack, onOpenCards, onOpenReviewed }: CrsHeaderProps) {
  const equipment = orNothing(submittal?.equipment_type) || run.equipment_tags.join(", ");
  const revision = orNothing(submittal?.revision);
  const code = orNothing(run.engineer_final_code) || orNothing(run.recommended_code);
  const canSign = unopened.length === 0 && !sign.busy;
  const primary = "rounded-[var(--radius-sm)] bg-signal-500 px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50";
  const secondary = "rounded-[var(--radius-sm)] border border-ink-600 px-3 py-2 text-sm text-slateish-100 disabled:opacity-50";
  return (
    <header className="space-y-3">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        <button type="button" onClick={onBack} className="text-signal-300 underline-offset-2 hover:underline">← Reviews</button>
        <button type="button" onClick={onOpenCards} className="text-signal-300 underline-offset-2 hover:underline">Open cards view</button>
        {onOpenReviewed && (
          <button type="button" onClick={onOpenReviewed} className="text-signal-300 underline-offset-2 hover:underline">How this was reviewed</button>
        )}
      </div>
      <div>
        <h1 id="crs-title" className="break-words text-2xl font-semibold text-slateish-100">{run.submittal_filename ?? "Review"}</h1>
        <p className="text-sm text-slateish-400">
          {[equipment ? `Equipment: ${equipment}` : "", revision ? `Revision ${revision}` : ""].filter(Boolean).join(" · ")}
        </p>
      </div>
      <p className="text-slateish-200" data-testid="crs-headline">{crsHeadline(run, counts)}</p>
      {code && (
        <p className="text-sm text-slateish-300" data-testid="crs-code">
          <span className="font-semibold text-slateish-100">{run.engineer_final_code ? "Code: " : "Proposed code: "}{code}</span>
          {orNothing(run.recommended_reason) ? `. ${orNothing(run.recommended_reason)}` : ""}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {acceptAll.confirming ? (
          <span className="flex flex-wrap items-center gap-2 text-sm text-slateish-200" role="status">
            {remaining} {remaining === 1 ? "comment" : "comments"} will be kept. Rows marked "Needs you" are not touched.
            <button type="button" onClick={acceptAll.onConfirm} className={primary} disabled={remaining === 0}>Yes, keep them</button>
            <button type="button" onClick={acceptAll.onCancel} className={secondary}>Cancel</button>
          </span>
        ) : (
          <button type="button" onClick={acceptAll.onAsk} className={secondary} disabled={remaining === 0}>
            Accept all remaining Comments{remaining > 0 ? ` (${remaining})` : ""}
          </button>
        )}
        {acceptAll.canUndo && (
          <span className="flex items-center gap-2 text-sm text-slateish-300" role="status">
            {acceptAll.kept !== null ? `${acceptAll.kept} kept.` : ""}
            <button type="button" onClick={acceptAll.onUndo} className="text-signal-300 underline-offset-2 hover:underline">Undo</button>
          </span>
        )}
        <span className="ml-auto flex flex-wrap items-center gap-2">
          <button type="button" onClick={sign.onWorkingCopy} disabled={sign.busy} className={secondary}>Download working copy</button>
          <button type="button" onClick={sign.onSign} disabled={!canSign} className={primary}
            title={unopened.length > 0 ? `Open the ${unopened.length} "Needs you" ${unopened.length === 1 ? "row" : "rows"} first.` : undefined}>
            {sign.busy ? "Exporting…" : "Sign and export"}
          </button>
        </span>
      </div>
      {localDecisions > 0 && (
        <p className="text-xs text-warn-500" data-testid="sign-local-note">
          Your {localDecisions} {localDecisions === 1 ? "decision" : "decisions"} on this screen (Keep, edited wording, Remove)
          {" "}{localDecisions === 1 ? "is" : "are"} not in the exported file yet: Sign and export issues the sheet as the record holds it.
        </p>
      )}
      {unopened.length > 0 && (
        <p className="text-xs text-slateish-400" data-testid="sign-waits">
          Sign and export waits until you have opened the {unopened.length} {unopened.length === 1 ? "row" : "rows"} marked "Needs you".
        </p>
      )}
      <p className="text-xs text-slateish-500">
        Keep, edited wording and Remove are held on this screen only for now; they are not yet saved to the record.
      </p>
      {sign.message && <p role="status" className="text-sm text-signal-300">{sign.message}</p>}
      {sign.error && (
        <p role="alert" className="rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-sm text-danger-500">{sign.error}</p>
      )}
    </header>
  );
}
