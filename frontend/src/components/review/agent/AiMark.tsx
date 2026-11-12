/**
 * A small mark on the list page: "AI review: N lines" when the review has an
 * AI review. N counts every line of that review except those that do not
 * apply (the review's own lines, nothing else); nothing is drawn while it is
 * not known, and nothing for a review without an AI review.
 */
import { useEffect, useState } from "react";

import { agentReview } from "../../../api/agentReview";

export function AiMark({ runId }: { runId: string }) {
  const [lines, setLines] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    setLines(null);
    void agentReview.summary(runId).then((r) => {
      if (!live || !r.ok) return;
      const total = Object.entries(r.data.counts_by_class)
        .filter(([k]) => k !== "Not applicable")
        .reduce((sum, [, n]) => sum + n, 0);
      setLines(total);
    }, () => undefined);
    return () => { live = false; };
  }, [runId]);
  if (lines === null) return null;
  return (
    <span data-testid="ai-mark" className="rounded-full border border-signal-500/50 px-2 py-0.5 text-xs font-semibold text-signal-300">
      AI review: {lines.toLocaleString()} {lines === 1 ? "line" : "lines"}
    </span>
  );
}
