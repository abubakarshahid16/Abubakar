/**
 * The evidence drawer, the small version (order 95 piece 2). Piece 4
 * replaces it with the page image + clause + comparison + history drawer
 * (spec 1.3). Here: the row's reason first on a "Needs you" row, what was
 * noticed, the rule, the comment, the datasheet page with the value
 * underlined, and a link to the same point on the cards view.
 *
 * Read only. Decisions stay on the row.
 */
import { useEffect, useRef } from "react";

import { orNothing } from "../reviewFormat";
import { SheetPageImage } from "../sheet/SheetPageImage";
import { cardTitle, trustLine } from "../sheet/sheetCards";
import type { CrsRow } from "./crsRows";
import type { TierReason } from "./tiers";

const REASON_WORDS: Record<TierReason, string> = {
  "page not read": "The reader did not read this page into fields, so the value may still be on the page. Read the page yourself.",
  "standard not in library": "The standard this comment rests on is not in the library, so the clause could not be checked. Upload it, or decide from the datasheet.",
  "AI guess": "The datasheet field was paired with this clause by an AI guess that nobody has confirmed. Check that the field is the one the clause means.",
  "rule not proven": "The rule behind this row has not been proven yet, so its answer is not trusted on its own. Check it against the standard.",
  "safety field": "This is a safety field. It meets the standard, but it is shown for your own tick before it goes on the record.",
  "condition unsettled": "The rule has a condition the computer could not settle. Decide whether it applies here.",
  "value conflict": "The datasheet gives two values for this field. Decide which one counts.",
  "unit unknown": "The unit of the value could not be read, so it was not compared. Check the unit on the page.",
};

export interface CrsEvidenceDrawerProps {
  row: CrsRow;
  runId: string;
  standardNames: Map<string, string>;
  onClose: () => void;
  onOpenCards: () => void;
  /** The element to give the keyboard back to on close. */
  returnTo: HTMLElement | null;
}

export function CrsEvidenceDrawer({ row, runId, standardNames, onClose, onOpenCards, returnTo }: CrsEvidenceDrawerProps) {
  const closeRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    closeRef.current?.focus();
    return () => { returnTo?.focus?.(); };
  }, [row.key, returnTo]);
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") { e.preventDefault(); onClose(); } }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const leader = row.findings[0];
  const card = { key: row.key, findings: row.findings, state: row.priorState, page: row.page, pages: [] };
  const standard = standardNames.get(leader.standard_document_id ?? "") ?? "";
  const title = cardTitle(card);
  const h = "text-xs font-semibold uppercase tracking-wide text-slateish-400";
  return (
    <aside role="dialog" aria-modal="false" aria-labelledby="crs-drawer-title"
      className="fixed inset-y-0 right-0 z-30 w-full max-w-xl overflow-y-auto border-l border-ink-700 bg-ink-900 p-4 shadow-xl sm:w-[36rem]">
      <div className="flex items-start gap-3">
        <h2 id="crs-drawer-title" className="flex-1 text-base font-semibold text-slateish-100">
          {row.commentNo ? `Comment ${row.commentNo}: ` : ""}{title}
        </h2>
        <button ref={closeRef} type="button" onClick={onClose} aria-label="Close evidence"
          className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-1 text-sm text-slateish-200">Close</button>
      </div>
      <div className="mt-3 space-y-4">
        {row.tier.reason && (
          <section className="rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 p-3">
            <h3 className={h}>Why it needs you: {row.tier.reason}</h3>
            <p className="mt-1 text-sm text-slateish-100">{REASON_WORDS[row.tier.reason]}</p>
          </section>
        )}
        <section>
          <h3 className={h}>We noticed</h3>
          <p className="mt-1 text-sm text-slateish-200">{orNothing(leader.finding)}</p>
          {orNothing(leader.contractor_evidence_text) && (
            <blockquote className="mt-1 border-l-2 border-ink-600 pl-2 text-xs text-slateish-300">
              "{orNothing(leader.contractor_evidence_text)}"{leader.contractor_page ? ` (datasheet p. ${leader.contractor_page})` : ""}
            </blockquote>
          )}
        </section>
        <section>
          <h3 className={h}>The rule</h3>
          <p className="mt-1 text-sm text-slateish-200">{orNothing(leader.requirement_source_text) || orNothing(leader.requirement)}</p>
          {(standard || leader.standard_clause) && (
            <p className="mt-1 text-xs text-slateish-400">
              {[standard, leader.standard_clause ? `clause ${leader.standard_clause}` : "", leader.standard_page ? `p. ${leader.standard_page}` : ""].filter(Boolean).join(", ")}
            </p>
          )}
        </section>
        <section>
          <h3 className={h}>Our comment</h3>
          <p className="mt-1 whitespace-pre-wrap text-sm text-slateish-100">{orNothing(leader.engineer_comment) || orNothing(leader.required_action)}</p>
        </section>
        {orNothing(leader.ai_rationale) && (
          <section>
            <h3 className={h}>Why the computer said so</h3>
            <p className="mt-1 whitespace-pre-wrap text-xs text-slateish-300">{orNothing(leader.ai_rationale)}</p>
          </section>
        )}
        <p className="text-xs text-slateish-500">{trustLine(card)}</p>
        {typeof leader.contractor_page === "number" && (
          <SheetPageImage runId={runId} page={leader.contractor_page}
            marks={row.findings.filter((f) => f.contractor_page === leader.contractor_page).map((f) => ({ findingId: f.id, state: "open" as const }))} />
        )}
        <button type="button" onClick={onOpenCards} className="text-sm text-signal-300 underline-offset-2 hover:underline">
          Open this point on the cards view
        </button>
      </div>
    </aside>
  );
}
