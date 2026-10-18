/**
 * The evidence drawer (order 95 piece 4, absorbing order 94a; Part of #967).
 * The row's reason first on a "Needs you" row, then one line comparing what
 * the datasheet says with what the rule asks, what was noticed, the rule and
 * its clause, the comment, the datasheet page (zoomable, value underlined),
 * and what happened to the comment so far.
 *
 * COMMENT-DRIVEN NAVIGATION for long documents: Previous / Next comment
 * (J / K), "Page N of M" with a strip of the pages that carry a comment plus
 * the first and last page, a jump box, and PageUp / PageDown between comment
 * pages. A page with no comment can still be looked at; it is said so.
 *
 * Read only. Decisions stay on the row.
 */
import { useEffect, useRef, useState } from "react";

import { orNothing } from "../reviewFormat";
import { SheetPageImage } from "../sheet/SheetPageImage";
import { cardTitle, trustLine } from "../sheet/sheetCards";
import type { CrsRow } from "./crsRows";
import { comparisonLine, historyOf, pagerStrip, parsePage, stepPage } from "./evidenceNav";
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
  /** Where this row sits in the list shown, and how to move along it. */
  nav?: { index: number; total: number; onPrev: (() => void) | null; onNext: (() => void) | null };
  /** The document's pages: its page count (null when not known), the pages
   *  that carry a comment, and how to open the first comment on a page. */
  pager?: { pageCount: number | null; commentPages: number[]; onPage: (page: number) => boolean };
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}

export function CrsEvidenceDrawer({ row, runId, standardNames, onClose, onOpenCards, returnTo, nav, pager }: CrsEvidenceDrawerProps) {
  const closeRef = useRef<HTMLButtonElement | null>(null);
  // The page shown: the row's own, until the engineer looks at another one.
  const [viewPage, setViewPage] = useState<number | null>(row.page);
  const [jump, setJump] = useState("");
  const [jumpError, setJumpError] = useState<string | null>(null);
  const [viewFor, setViewFor] = useState(row.key);
  if (viewFor !== row.key) { setViewFor(row.key); setViewPage(row.page); setJumpError(null); }
  useEffect(() => {
    closeRef.current?.focus();
    return () => { returnTo?.focus?.(); };
  }, [row.key, returnTo]);

  const pageCount = pager?.pageCount ?? null;
  function goPage(page: number) {
    setJumpError(null);
    if (!pager?.onPage(page)) setViewPage(page);
  }
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") { e.preventDefault(); onClose(); return; }
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      // Page keys mean nothing in the page box, so they work from it too.
      const paging = e.key === "PageDown" || e.key === "PageUp";
      if (isTyping(e.target) && !(paging && (e.target as HTMLElement).id === "crs-drawer-jump")) return;
      if ((e.key === "j" || e.key === "J") && nav?.onNext) { e.preventDefault(); nav.onNext(); }
      else if ((e.key === "k" || e.key === "K") && nav?.onPrev) { e.preventDefault(); nav.onPrev(); }
      else if (paging && pager) {
        const next = stepPage(pager.commentPages, viewPage, e.key === "PageDown" ? 1 : -1);
        if (next !== null) { e.preventDefault(); if (!pager.onPage(next)) setViewPage(next); }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, nav, pager, viewPage]);

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
      {nav && (
        <nav aria-label="Comments" className="mt-2 flex items-center gap-2 text-sm text-slateish-300">
          <button type="button" onClick={nav.onPrev ?? undefined} disabled={!nav.onPrev}
            className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-0.5 disabled:opacity-40">← Previous</button>
          <span data-testid="drawer-position">Row {nav.index + 1} of {nav.total}</span>
          <button type="button" onClick={nav.onNext ?? undefined} disabled={!nav.onNext}
            className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-0.5 disabled:opacity-40">Next →</button>
          <span className="text-xs text-slateish-500">J / K</span>
        </nav>
      )}
      <div className="mt-3 space-y-4">
        {row.tier.reason && (
          <section className="rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 p-3">
            <h3 className={h}>Why it needs you: {row.tier.reason}</h3>
            <p className="mt-1 text-sm text-slateish-100">{REASON_WORDS[row.tier.reason]}</p>
          </section>
        )}
        {comparisonLine(leader) && (
          <p data-testid="drawer-comparison" className="rounded-[var(--radius-sm)] border border-ink-700 bg-ink-950/40 p-2 text-sm text-slateish-100">
            {comparisonLine(leader)}
          </p>
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
        {pager && (
          <section aria-label="Pages" className="space-y-2">
            <p className="text-sm text-slateish-200" data-testid="drawer-page">
              {viewPage === null ? "This comment has no page." : `Page ${viewPage}${pageCount !== null ? ` of ${pageCount}` : ""}`}
              {viewPage !== null && viewPage !== row.page && !pager.commentPages.includes(viewPage) ? " - no comment on this page" : ""}
            </p>
            <div className="flex flex-wrap gap-1" data-testid="drawer-strip">
              {pagerStrip(pager.commentPages, pageCount).map((p) => (
                <button key={p} type="button" onClick={() => goPage(p)} aria-current={p === viewPage ? "page" : undefined}
                  className={`min-w-8 rounded-[var(--radius-sm)] border px-1.5 py-0.5 text-xs ${p === viewPage ? "border-signal-400 text-signal-300" : "border-ink-600 text-slateish-300"}`}
                  title={pager.commentPages.includes(p) ? `Page ${p}: has a comment` : `Page ${p}`}>{p}</button>
              ))}
            </div>
            <form className="flex items-center gap-2 text-xs text-slateish-300"
              onSubmit={(e) => {
                e.preventDefault();
                const page = parsePage(jump, pageCount);
                if (page === null) { setJumpError(pageCount !== null ? `Type a page from 1 to ${pageCount}.` : "Type a page number."); return; }
                setJump(""); goPage(page);
              }}>
              <label htmlFor="crs-drawer-jump">Go to page</label>
              <input id="crs-drawer-jump" inputMode="numeric" value={jump} onChange={(e) => setJump(e.target.value)}
                className="w-16 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-950 px-1 py-0.5 text-slateish-100" />
              <button type="submit" className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-0.5">Go</button>
              <span className="text-slateish-500">PageUp / PageDown: comment pages</span>
            </form>
            {jumpError && <p role="alert" className="text-xs text-danger-500">{jumpError}</p>}
          </section>
        )}
        {typeof viewPage === "number" && (
          <SheetPageImage runId={runId} page={viewPage}
            marks={row.findings.filter((f) => f.contractor_page === viewPage).map((f) => ({ findingId: f.id, state: "open" as const }))} />
        )}
        {historyOf(row.findings).length > 0 && (
          <section>
            <h3 className={h}>History</h3>
            <ol className="mt-1 space-y-0.5 text-xs text-slateish-300" data-testid="drawer-history">
              {historyOf(row.findings).map((e, i) => (
                <li key={i}>{e.when ? <span className="text-slateish-500">{e.when}: </span> : null}{e.what}</li>
              ))}
            </ol>
          </section>
        )}
        <button type="button" onClick={onOpenCards} className="text-sm text-signal-300 underline-offset-2 hover:underline">
          Open this point on the cards view
        </button>
      </div>
    </aside>
  );
}
