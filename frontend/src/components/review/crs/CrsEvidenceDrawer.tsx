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
 * The history reads the run's decision record (`GET .../crs/decisions`),
 * so an earlier decision on the same comment stays listed with its reason.
 *
 * Read only. Decisions stay on the row.
 */
import { type ReactNode, useEffect, useRef, useState } from "react";

import { reviews as reviewsApi } from "../../../api/client";
import type { CrsIssueDecision } from "../../../types/api";
import { ReasonText } from "../ReasonText";
import { SENSE_CHECK_RULE, isSenseCheck } from "../reasonWords";
import { orNothing } from "../reviewFormat";
import { SheetPageImage } from "../sheet/SheetPageImage";
import { cardTitle, trustLine } from "../sheet/sheetCards";
import type { CrsRow } from "./crsRows";
import { comparisonLine, historyOf, pagerStrip, parsePage, stepPage } from "./evidenceNav";
import { REASON_WORDS } from "../workspace/plainWords";

export interface CrsEvidenceDrawerProps {
  row: CrsRow;
  runId: string;
  standardNames: Map<string, string>;
  onClose: () => void;
  /** The old cards view of this point. Absent inside the review workspace:
   *  the old review screens are gone there (owner, 19 Oct 2026). */
  onOpenCards?: () => void;
  /** The element to give the keyboard back to on close. */
  returnTo: HTMLElement | null;
  /** Where this row sits in the list shown, and how to move along it. */
  nav?: {
    index: number; total: number; onPrev: (() => void) | null; onNext: (() => void) | null;
    /** v2.1: the position line in full ("Comment 3 of 12"). Absent: "Item N of M", as before. */
    position?: string;
  };
  /** The document's pages: its page count (null when not known), the pages
   *  that carry a comment, and how to open the first comment on a page. */
  pager?: { pageCount: number | null; commentPages: number[]; onPage: (page: number) => boolean };
  /** Optional block shown under the row's reason (the review workspace's
   *  plain words with their codes under "Details"). Absent: nothing changes. */
  extra?: ReactNode;
  /** v2.2 round 2: the "J / K" hint; the workspace's Simple view hides it. */
  showKeys?: boolean;
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}

export function CrsEvidenceDrawer({ row, runId, standardNames, onClose, onOpenCards, returnTo, nav, pager, extra, showKeys = true }: CrsEvidenceDrawerProps) {
  const closeRef = useRef<HTMLButtonElement | null>(null);
  // The page shown: the row's own, until the engineer looks at another one.
  const [viewPage, setViewPage] = useState<number | null>(row.page);
  const [jump, setJump] = useState("");
  const [jumpError, setJumpError] = useState<string | null>(null);
  // The run's decision record; null until loaded, "failed" when it could not be.
  const [decisions, setDecisions] = useState<CrsIssueDecision[] | null | "failed">(null);
  useEffect(() => {
    let live = true;
    reviewsApi.crsDecisions(runId)
      .then((r) => { if (live) setDecisions(r.ok ? r.data.decisions : "failed"); })
      .catch(() => { if (live) setDecisions("failed"); });
    return () => { live = false; };
  }, [runId]);
  const history = historyOf(row.findings, Array.isArray(decisions) ? decisions : null);
  const [viewFor, setViewFor] = useState(row.key);
  if (viewFor !== row.key) { setViewFor(row.key); setViewPage(row.page); setJumpError(null); }
  // Order 117: Close takes the keyboard once, when the drawer opens; moving
  // to another row leaves focus where it is; closing gives it back to the
  // element that opened the drawer (the latest one the screen named).
  const returnRef = useRef(returnTo);
  useEffect(() => { returnRef.current = returnTo; }, [returnTo]);
  useEffect(() => {
    closeRef.current?.focus();
    return () => { returnRef.current?.focus?.(); };
  }, []);

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
          <span data-testid="drawer-position">{nav.position ?? `Item ${nav.index + 1} of ${nav.total}`}</span>
          <button type="button" onClick={nav.onNext ?? undefined} disabled={!nav.onNext}
            className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-0.5 disabled:opacity-40">Next →</button>
          {showKeys && <span className="text-xs text-slateish-500">J / K</span>}
        </nav>
      )}
      <div className="mt-3 space-y-4">
        {row.tier.reason && (
          <section className="rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 p-3">
            <h3 className={h}>Why it needs you: {row.tier.reason}</h3>
            <p className="mt-1 text-sm text-slateish-100">{REASON_WORDS[row.tier.reason]}</p>
          </section>
        )}
        {extra}
        {comparisonLine(leader) && (
          <p data-testid="drawer-comparison" className="rounded-[var(--radius-sm)] border border-ink-700 bg-ink-950/40 p-2 text-sm text-slateish-100">
            {comparisonLine(leader)}
          </p>
        )}
        <section>
          <h3 className={h}>We noticed</h3>
          <p className="mt-1 text-sm text-slateish-200"><ReasonText text={orNothing(leader.finding)} /></p>
          {orNothing(leader.contractor_evidence_text) && (
            <blockquote className="mt-1 border-l-2 border-ink-600 pl-2 text-xs text-slateish-300">
              "{orNothing(leader.contractor_evidence_text)}"{leader.contractor_page ? ` (datasheet p. ${leader.contractor_page})` : ""}
            </blockquote>
          )}
        </section>
        <section>
          <h3 className={h}>The rule</h3>
          <p className="mt-1 text-sm text-slateish-200">
            {isSenseCheck(leader) ? SENSE_CHECK_RULE : orNothing(leader.requirement_source_text) || orNothing(leader.requirement)}
          </p>
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
            <p className="mt-1 whitespace-pre-wrap text-xs text-slateish-300"><ReasonText text={orNothing(leader.ai_rationale)} /></p>
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
        {history.length > 0 && (
          <section>
            <h3 className={h}>History</h3>
            <ol className="mt-1 space-y-0.5 text-xs text-slateish-300" data-testid="drawer-history">
              {history.map((e, i) => (
                <li key={i}>{e.when ? <span className="text-slateish-500">{e.when}: </span> : null}{e.what}</li>
              ))}
            </ol>
            {decisions === "failed" && (
              <p className="mt-1 text-xs text-slateish-500" data-testid="drawer-history-partial">
                The decision record could not be loaded, so earlier decisions and their reasons may be missing here.
              </p>
            )}
          </section>
        )}
        {onOpenCards && (
          <button type="button" onClick={onOpenCards} className="text-sm text-signal-300 underline-offset-2 hover:underline">
            Open this point on the cards view
          </button>
        )}
      </div>
    </aside>
  );
}
