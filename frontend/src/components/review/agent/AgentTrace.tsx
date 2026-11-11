/**
 * The trace of one line: where it came from and which checks it passed.
 * Paper quote and rule quote are shown as the server sent them.
 */
import { useEffect, useState } from "react";

import { agentReview } from "../../../api/agentReview";
import type { AgentTrace as Trace } from "../../../types/api";

export function AgentTrace({ runId, itemId, onClose }: { runId: string; itemId: string; onClose: () => void }) {
  const [trace, setTrace] = useState<Trace | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setTrace(null);
    setError(null);
    void agentReview.trace(runId, itemId).then((r) => {
      if (!live) return;
      if (r.ok) setTrace(r.data); else setError(r.error.message);
    });
    return () => { live = false; };
  }, [runId, itemId]);

  return (
    <aside aria-label="Trace of the chosen line" data-testid="agent-trace"
      className="space-y-2 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-850 p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold text-slateish-100">Trace</h3>
        <button type="button" onClick={onClose} className="text-signal-300 underline-offset-2 hover:underline">Close trace</button>
      </div>
      {error && <p role="alert" className="text-red-400">{error}</p>}
      {!trace && !error && <p role="status" className="text-slateish-400">Reading the trace…</p>}
      {trace && (
        <>
          <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-[max-content_1fr]">
            <dt className="text-slateish-400">Page</dt><dd>{trace.page != null ? trace.page : "no single page"}</dd>
            <dt className="text-slateish-400">Paper quote</dt><dd className="break-words">{trace.paper_quote}</dd>
            <dt className="text-slateish-400">Rule quote</dt><dd className="break-words">{trace.rule_quote}</dd>
            {trace.other_quote && (<><dt className="text-slateish-400">Second quote</dt><dd className="break-words">{trace.other_quote}</dd></>)}
            <dt className="text-slateish-400">Rule book</dt><dd>{trace.rule_book}</dd>
            <dt className="text-slateish-400">Clause</dt><dd>{trace.clause}</dd>
            <dt className="text-slateish-400">Model</dt><dd>{trace.model}</dd>
            <dt className="text-slateish-400">Reason</dt><dd className="break-words">{trace.reason}</dd>
          </dl>
          <h4 className="font-semibold text-slateish-200">Checks this line passed through</h4>
          {trace.gate.length === 0 ? <p className="text-slateish-400">No check steps were recorded.</p> : (
            <ol className="list-decimal space-y-1 pl-5">
              {trace.gate.map((g, i) => (
                <li key={`${g.step}-${i}`}><span className="font-medium">{g.step}</span>: {g.outcome}{g.reason ? ` (${g.reason})` : ""}</li>
              ))}
            </ol>
          )}
        </>
      )}
    </aside>
  );
}
