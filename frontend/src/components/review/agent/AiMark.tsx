/**
 * A small mark on the list page: "AI review: N lines" when the newest review
 * of the file has an AI review. N counts every line of that review except
 * those that do not apply. When the newest review has none but one of the
 * file's few next-newest reviews has, a small hint says so. Nothing is drawn
 * while it is not known, and nothing for a file with no AI review.
 */
import { useEffect, useState } from "react";

import { agentReview } from "../../../api/agentReview";

/** How many older reviews of a file are looked at for the hint. */
export const EARLIER_LOOKED_AT = 5;
export const EARLIER_HINT = "An earlier review of this file has an AI review";

type Mark = { kind: "lines"; lines: number } | { kind: "earlier" } | null;

export function AiMark({ runId, earlierRunIds = [] }: { runId: string; earlierRunIds?: string[] }) {
  const [mark, setMark] = useState<Mark>(null);
  const earlierKey = earlierRunIds.slice(0, EARLIER_LOOKED_AT).join("|");
  useEffect(() => {
    let live = true;
    setMark(null);
    void (async () => {
      try {
        const own = await agentReview.summary(runId);
        if (!live) return;
        if (own.ok) {
          const total = Object.entries(own.data.counts_by_class)
            .filter(([k]) => k !== "Not applicable")
            .reduce((sum, [, n]) => sum + n, 0);
          setMark({ kind: "lines", lines: total });
          return;
        }
        for (const id of earlierKey ? earlierKey.split("|") : []) {
          const older = await agentReview.summary(id);
          if (!live) return;
          if (older.ok) { setMark({ kind: "earlier" }); return; }
        }
      } catch { /* nothing is drawn */ }
    })();
    return () => { live = false; };
  }, [runId, earlierKey]);
  if (mark === null) return null;
  if (mark.kind === "earlier") {
    return <span data-testid="ai-earlier-hint" className="text-xs text-slateish-400">{EARLIER_HINT}</span>;
  }
  return (
    <span data-testid="ai-mark" className="rounded-full border border-signal-500/50 px-2 py-0.5 text-xs font-semibold text-signal-300">
      AI review: {mark.lines.toLocaleString()} {mark.lines === 1 ? "line" : "lines"}
    </span>
  );
}
