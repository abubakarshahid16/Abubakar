/** The paper's reviews, newest first, each marked "General review" or "Earlier version" (piece D's history route). Read when drawn. */
import { useEffect, useState } from "react";

import { type PaperHistory, generalReview } from "../../../api/generalReview";

export function GeneralHistory({ documentId }: { documentId: string }) {
  const [history, setHistory] = useState<PaperHistory | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void generalReview.history(documentId).then((r) => {
      if (!live) return;
      if (r.ok) setHistory(r.data); else setProblem(r.error.message);
    });
    return () => { live = false; };
  }, [documentId]);
  if (problem) return <p role="alert" className="text-xs text-danger-500">{problem}</p>;
  if (!history) return <p className="text-xs text-slateish-400">Reading the history…</p>;
  return (
    <section data-testid="general-history" aria-label="History" className="space-y-1">
      <h3 className="font-semibold text-slateish-100">History ({history.runs.length} reviews; {history.boundary})</h3>
      <ul className="space-y-1 text-xs text-slateish-300">
        {history.runs.map((r) => (
          <li key={r.run_id}>
            <span className="font-semibold">{r.version === "general" ? "Current method" : "Earlier version"}</span>
            {" "}({r.part}, {r.status}{r.finished_at ? `, ${r.finished_at.slice(0, 10)}` : ""}{r.points != null ? `, ${r.points} points` : ""})
          </li>
        ))}
      </ul>
    </section>
  );
}
