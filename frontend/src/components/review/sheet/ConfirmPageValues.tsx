/**
 * "Confirm page values" (order 161 item A, approved by the owner as order 164.1).
 *
 * One button per page opens the values the program read on that page: the
 * field, the value with its unit, and the quote it came from. NOTHING IS
 * PRE-TICKED: the engineer ticks what they checked against the page, or uses
 * "Tick all on this page" after looking. A value two readers read differently
 * (a conflict) is listed first and is NEVER bulk-ticked; it has its own button.
 * The click records the engineer's confirmation (the server writes it, all or
 * none) and the review is judged again, so the sentence that follows says how
 * many findings of this review now have a verdict. There is no un-confirm:
 * that is how the server records it, and this screen offers no silent undo.
 */
import { useCallback, useState } from "react";

import { reviews as reviewsApi } from "../../../api/client";
import type { PageFact } from "../../../types/api";
import { resultLine } from "./confirmValues";

type Load = { kind: "idle" } | { kind: "loading" } | { kind: "error"; message: string } | { kind: "ready"; facts: PageFact[] };

function shown(f: PageFact): string {
  return [f.value ?? "no value", f.unit].filter(Boolean).join(" ");
}

export function ConfirmPageValues({ runId, page, onConfirmed }: {
  runId: string;
  page: number;
  /** Called after a confirmation was recorded, so the cards are read again. */
  onConfirmed?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [load, setLoad] = useState<Load>({ kind: "idle" });
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const read = useCallback(async () => {
    setLoad({ kind: "loading" });
    const r = await reviewsApi.pageFacts(runId, page);
    if (!r.ok) { setLoad({ kind: "error", message: r.error.message }); return; }
    setLoad({ kind: "ready", facts: r.data.facts });
  }, [runId, page]);

  // A new page is a new list: the parent keys this component by run and page,
  // so ticks and an answer are never carried over to another page.

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && load.kind === "idle") void read();
  }

  async function confirm(ids: string[]) {
    if (ids.length === 0 || busy) return;
    setBusy(true); setProblem(null);
    const r = await reviewsApi.confirmPageFacts(runId, ids);
    setBusy(false);
    if (!r.ok) { setProblem(r.error.message); return; }
    setResult(resultLine(r.data));
    setTicked(new Set());
    await read();
    onConfirmed?.();
  }

  const facts = load.kind === "ready" ? load.facts : [];
  const conflicts = facts.filter((f) => f.conflict && !f.confirmed);
  const waiting = facts.filter((f) => !f.conflict && f.needs_check && !f.confirmed);
  const done = facts.filter((f) => f.confirmed);
  const others = facts.filter((f) => !f.conflict && !f.needs_check && !f.confirmed);

  function tick(id: string, on: boolean) {
    setTicked((cur) => { const next = new Set(cur); if (on) next.add(id); else next.delete(id); return next; });
  }

  return (
    <div className="space-y-2" data-testid="confirm-page-values">
      <button
        type="button" onClick={toggle} aria-expanded={open}
        className="rounded-[var(--radius-sm)] border border-ink-700 px-3 py-1 text-sm text-slateish-200 hover:border-ink-600"
      >
        Confirm page values
      </button>

      {open && (
        <section aria-label={`Values read on page ${page}`} className="space-y-3 rounded-[var(--radius-sm)] border border-ink-700 p-3 text-sm">
          <p className="text-xs text-slateish-400">
            The values the program read on page {page} of this datasheet. Tick the ones you have checked against the page.
          </p>
          {load.kind === "loading" && <p role="status" className="text-slateish-400">Reading the values on this page…</p>}
          {load.kind === "error" && <p role="alert" className="text-danger-500">{load.message}</p>}
          {load.kind === "ready" && facts.length === 0 && (
            <p className="text-slateish-400">No value was read on this page.</p>
          )}

          {conflicts.length > 0 && (
            <div className="space-y-2">
              <h4 className="font-medium text-warn-500">Read two different ways: confirm one at a time</h4>
              <ul className="space-y-2">
                {conflicts.map((f) => (
                  <li key={f.fact_id} className="space-y-1">
                    <p><span className="font-medium">{f.field}</span>: {shown(f)}</p>
                    {f.quote && <p className="text-xs text-slateish-400">“{f.quote}”</p>}
                    <button
                      type="button" disabled={busy} onClick={() => void confirm([f.fact_id])}
                      aria-label={`Confirm this value: ${f.field}`}
                      className="rounded-[var(--radius-sm)] border border-ink-700 px-2 py-0.5 text-xs hover:border-ink-600"
                    >
                      Confirm this value
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {(waiting.length > 0 || others.length > 0) && (
            <div className="space-y-2">
              <ul className="space-y-2">
                {[...waiting, ...others].map((f) => (
                  <li key={f.fact_id}>
                    <label className="flex items-start gap-2">
                      <input
                        type="checkbox" checked={ticked.has(f.fact_id)}
                        onChange={(e) => tick(f.fact_id, e.target.checked)}
                      />
                      <span>
                        <span className="font-medium">{f.field}</span>: {shown(f)}
                        {f.quote && <span className="block text-xs text-slateish-400">“{f.quote}”</span>}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button" disabled={busy}
                  onClick={() => setTicked(new Set([...waiting, ...others].map((f) => f.fact_id)))}
                  className="rounded-[var(--radius-sm)] border border-ink-700 px-2 py-0.5 text-xs hover:border-ink-600"
                >
                  Tick all on this page
                </button>
                <button
                  type="button" disabled={busy || ticked.size === 0}
                  onClick={() => void confirm([...ticked])}
                  className="rounded-[var(--radius-sm)] border border-signal-500 px-3 py-0.5 text-xs text-slateish-100 disabled:opacity-50"
                >
                  {`Confirm ${ticked.size} value${ticked.size === 1 ? "" : "s"}`}
                </button>
              </div>
            </div>
          )}

          {done.length > 0 && (
            <p className="text-xs text-slateish-400">
              Already confirmed on this page: {done.map((f) => f.field).join(", ")}.
            </p>
          )}
          {busy && (
            <p role="status" className="text-slateish-300">
              Judging this review again with your confirmation. This can take a few minutes; please wait.
            </p>
          )}
          {problem && <p role="alert" className="text-danger-500">{problem}</p>}
          {result && <p role="status" className="text-slateish-200">{result}</p>}
        </section>
      )}
    </div>
  );
}
