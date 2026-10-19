/**
 * OWNER: builder E (v2.2). "What changed since the last review", for the
 * engineer: the comments of this review side by side with an earlier review
 * of the same file, in three plain lists (new this time, gone since last
 * time, still open), each with its count and its boundary ("3 new comments
 * since the review of 12 Oct 2026").
 *
 * A dialog: the keyboard stays inside while it is open (Tab and Shift+Tab go
 * round), Escape or Close shuts it, and the opener gets the keyboard back
 * (PastReviewsList does that). Both reviews are read with the same reads the
 * workspace uses (`loadCommentLines`). A look only: nothing here changes a
 * decision, and there is no button that could.
 */
import { useEffect, useId, useRef, useState } from "react";

import type { CrsRow } from "../../crs/crsRows";
import { PlainErrorLine } from "../PlainErrorLine";
import type { PlainError } from "../plainError";
import { type RunComparison, compareRuns, comparisonLines, loadCommentLines, reviewDay } from "./compareRuns";

export interface CompareReviewsProps {
  currentRunId: string;
  earlierRunId: string;
  /** When the earlier review was made (its boundary on every count). */
  earlierAt: string | null;
  onClose: () => void;
}

type State = { kind: "loading" } | { kind: "error"; error: PlainError } | { kind: "ready"; result: RunComparison };

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"]), summary';

export const READ_ONLY_NOTE = "This is a look only. Comparing does not change any decision.";

function Line({ row }: { row: CrsRow }) {
  const where = [row.pageOrSection, row.item, row.clauseAndStandard].filter(Boolean).join(" · ");
  return (
    <li className="px-3 py-2 text-sm text-slateish-200">
      <p>{row.observation}</p>
      {row.requiredAction && <p className="mt-0.5 text-slateish-300">{row.requiredAction}</p>}
      {where && <p className="mt-0.5 text-xs text-slateish-400">{where}</p>}
    </li>
  );
}

function Group({ title, line, rows, testId, empty }: { title: string; line: string; rows: CrsRow[]; testId: string; empty: string }) {
  const headId = useId();
  return (
    <section aria-labelledby={headId} data-testid={testId} className="space-y-1">
      <h3 id={headId} className="text-sm font-semibold text-slateish-100">{title}</h3>
      <p className="text-xs text-slateish-400" data-testid={`${testId}-count`}>{line}</p>
      {rows.length === 0
        ? <p className="text-xs text-slateish-400">{empty}</p>
        : <ul className="divide-y divide-ink-700 rounded-[var(--radius-sm)] border border-ink-700">{rows.map((r) => <Line key={r.key} row={r} />)}</ul>}
    </section>
  );
}

export function CompareReviews({ currentRunId, earlierRunId, earlierAt, onClose }: CompareReviewsProps) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const box = useRef<HTMLDivElement>(null);
  const titleId = useId();

  useEffect(() => {
    let alive = true;
    setState({ kind: "loading" });
    void Promise.all([loadCommentLines(currentRunId), loadCommentLines(earlierRunId)]).then(([now, before]) => {
      if (!alive) return;
      if (!now.ok) { setState({ kind: "error", error: now.error }); return; }
      if (!before.ok) { setState({ kind: "error", error: before.error }); return; }
      setState({ kind: "ready", result: compareRuns(now.rows, before.rows) });
    });
    return () => { alive = false; };
  }, [currentRunId, earlierRunId]);

  useEffect(() => { box.current?.querySelector<HTMLElement>("[data-autofocus]")?.focus(); }, []);

  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Escape") { e.stopPropagation(); onClose(); return; }
    if (e.key !== "Tab" || !box.current) return;
    const items = [...box.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  const day = reviewDay(earlierAt);
  const lines = state.kind === "ready" ? comparisonLines(state.result, earlierAt) : null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4">
      <div
        ref={box} role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={onKeyDown}
        data-testid="compare-reviews"
        className="mt-8 w-full max-w-3xl space-y-4 rounded-[var(--radius-md)] border border-ink-700 bg-ink-900 p-4"
      >
        <header className="flex items-start gap-3">
          <h2 id={titleId} className="flex-1 text-lg font-semibold text-slateish-100">
            What changed since the review of {day || "the earlier date"}
          </h2>
          <button
            type="button" data-autofocus onClick={onClose}
            className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-sm text-slateish-200 hover:bg-ink-800"
          >
            Close
          </button>
        </header>
        <p className="text-xs text-slateish-400">{READ_ONLY_NOTE}</p>
        {state.kind === "loading" && <p role="status" className="text-sm text-slateish-300">Reading both reviews…</p>}
        {state.kind === "error" && <PlainErrorLine error={state.error} testId="compare-error" />}
        {state.kind === "ready" && lines && (
          <div className="space-y-4">
            <Group title="New this time" line={lines.added} rows={state.result.added} testId="compare-new"
              empty="No new comments." />
            <Group title="Gone since last time" line={lines.gone} rows={state.result.gone} testId="compare-gone"
              empty="No comments have gone." />
            <Group title="Still open" line={lines.still} rows={state.result.still} testId="compare-still"
              empty="No comments carried over." />
          </div>
        )}
      </div>
    </div>
  );
}
