import { useEffect, useState } from "react";

import { agentReview } from "../../../api/agentReview";

/** Under a button that gives a stored older file: what that file holds and where the complete CRS is. Null renders as nothing, never 0. */
export function OlderFileLine({ runId, where = "the download above" }: { runId: string; where?: string }) {
  const [n, setN] = useState<{ lines: number; points: number | null } | null>(null);
  useEffect(() => {
    let live = true;
    void agentReview.crsOlder(runId).then((r) => {
      if (live && r.ok && r.data.ai_lines) setN({ lines: r.data.ai_lines, points: r.data.paper_points });
    });
    return () => { live = false; };
  }, [runId]);
  if (!n) return null;
  return (
    <p data-testid="older-file-line" className="text-xs text-slateish-400">
      Older file: the AI review&apos;s {n.lines} lines only. The complete CRS{n.points ? ` (${n.points} points)` : ""} is {where}.
    </p>
  );
}
