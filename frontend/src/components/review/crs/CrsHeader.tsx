/**
 * The Sheet's header (order 95 piece 2, spec 1.2): document, equipment type,
 * revision, ONE headline line, the proposed code with its reason, and the
 * sheet actions.
 */
import type { DocumentRecord, ReviewRunSummary } from "../../../types/api";
import { CRS_SHEET_IS_DEFAULT, panelForReviewScreen } from "../../../routing";
import { NavLink } from "../../NavLink";
import { orNothing } from "../reviewFormat";
import { type CrsRow, type HeadlineFields, crsHeadline } from "./crsRows";
import type { TierCounts } from "./tiers";

export interface CrsHeaderProps {
  run: ReviewRunSummary;
  submittal: DocumentRecord | null;
  counts: TierCounts;
  /** The stored fields the headline reads (`headlineFieldsOf`). */
  headlineFields?: HeadlineFields;
  /** Who decided the tiers: "server" = the run summary (#1111), the one
   *  source; "screen" = this screen's own rules, because the summary did
   *  not answer (a server without the route, or a failed read). */
  tierSource?: "server" | "screen";
  /** Tier C rows the engineer has not opened yet (Sign waits for them). */
  unopened: CrsRow[];
  /** How many Comment rows "Accept all remaining" would keep right now. */
  remaining: number;
  /** Order 95 piece 6c: decisions taken on this screen and not saved yet,
   *  and the one press that saves them. */
  save: { unsaved: number; busy: boolean; onSave: () => void; message: string | null; error: string | null };
  acceptAll: { confirming: boolean; onAsk: () => void; onConfirm: () => void; onCancel: () => void; canUndo: boolean; onUndo: () => void; kept: number | null };
  sign: { busy: boolean; onSign: () => void; onWorkingCopy: () => void; message: string | null; error: string | null };
  onBack: () => void;
}

export function CrsHeader({
  run, submittal, counts, headlineFields, tierSource = "server", unopened, remaining, save, acceptAll, sign, onBack,
}: CrsHeaderProps) {
  const equipment = orNothing(submittal?.equipment_type) || run.equipment_tags.join(", ");
  const revision = orNothing(submittal?.revision);
  const code = orNothing(run.engineer_final_code) || orNothing(run.recommended_code);
  // Nothing is exported while a decision is on screen only (piece 6c).
  const canExport = save.unsaved === 0 && !save.busy && !sign.busy;
  const canSign = canExport && unopened.length === 0;
  const primary = "rounded-[var(--radius-sm)] bg-signal-500 px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50";
  const secondary = "rounded-[var(--radius-sm)] border border-ink-600 px-3 py-2 text-sm text-slateish-100 disabled:opacity-50";
  return (
    <header className="space-y-3">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        <button type="button" onClick={onBack} className="text-signal-300 underline-offset-2 hover:underline">← Reviews</button>
        {/* Order 95 piece 2: the way to the card view, through the app's own
            navigation; `/review/<run>/cards` now that the comment sheet is
            the default (order 115), plain `/review/<run>` if it ever is not. */}
        <NavLink view="review" recordId={run.review_run_id} panel={panelForReviewScreen("cards", CRS_SHEET_IS_DEFAULT)}
          className="text-signal-300 underline-offset-2 hover:underline">
          {CRS_SHEET_IS_DEFAULT ? "Open the card view" : "Back to the current review screen"}
        </NavLink>
        {/* Order 95 piece 5 (#1113): the run's audit page. Through the app's
            own navigation (a plain href reload would sign the reader out);
            an app that does not know the path yet shows its own
            "not an available route" page, nothing breaks. */}
        <NavLink view="review" recordId={run.review_run_id} panel="how" className="text-signal-300 underline-offset-2 hover:underline">
          How this was reviewed
        </NavLink>
      </div>
      <div>
        <h1 id="crs-title" className="break-words text-2xl font-semibold text-slateish-100">{run.submittal_filename ?? "Review"}</h1>
        <p className="text-sm text-slateish-400">
          {[equipment ? `Equipment: ${equipment}` : "", revision ? `Revision ${revision}` : ""].filter(Boolean).join(" · ")}
        </p>
      </div>
      <p className="text-slateish-200" data-testid="crs-headline">{crsHeadline(run, counts, headlineFields)}</p>
      {tierSource === "screen" && (
        <p className="text-xs text-slateish-500" data-testid="crs-tier-source">
          Tiers worked out on this screen: the run summary was not available from the server.
        </p>
      )}
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
          <button type="button" onClick={sign.onWorkingCopy} disabled={!canExport} className={secondary}>Download working copy</button>
          <button type="button" onClick={sign.onSign} disabled={!canSign} className={primary}
            title={unopened.length > 0 ? `Open the ${unopened.length} "Needs you" ${unopened.length === 1 ? "row" : "rows"} first.` : undefined}>
            {sign.busy ? "Exporting…" : "Sign and export"}
          </button>
        </span>
      </div>
      {(save.unsaved > 0 || save.busy) && (
        <p className="flex flex-wrap items-center gap-3 text-sm text-warn-500" data-testid="save-bar">
          <span>
            {save.unsaved} {save.unsaved === 1 ? "decision" : "decisions"} not saved yet. Sign and export waits until they are saved.
          </span>
          <button type="button" onClick={save.onSave} disabled={save.busy} className={primary}>
            {save.busy ? "Saving…" : "Save decisions"}
          </button>
        </p>
      )}
      {save.message && <p role="status" className="text-sm text-signal-300">{save.message}</p>}
      {save.error && (
        <p role="alert" className="rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-sm text-danger-500">{save.error}</p>
      )}
      {unopened.length > 0 && (
        <p className="text-xs text-slateish-400" data-testid="sign-waits">
          Sign and export waits until you have opened the {unopened.length} {unopened.length === 1 ? "row" : "rows"} marked "Needs you".
        </p>
      )}
      {sign.message && <p role="status" className="text-sm text-signal-300">{sign.message}</p>}
      {sign.error && (
        <p role="alert" className="rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-sm text-danger-500">{sign.error}</p>
      )}
    </header>
  );
}
