/** The paper's reviews, newest first, each marked "General review" or "Earlier version" (piece D's history route). Read when drawn. */
import { useEffect, useState } from "react";

import { type PaperHistory, generalReview } from "../../../api/generalReview";

/** A run's state and date in words (H's review of the owner's file, R6: "Current method" twice, with raw dates). */
const STATUS_WORDS: Record<string, string> = {
  completed: "complete", complete: "complete", done: "complete", stopped: "stopped early", running: "running", queued: "waiting to start",
  failed: "failed", cancelled: "cancelled",
};
export function dateWords(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso.slice(0, 10) : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

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
        {history.runs.map((r, i) => (
          <li key={r.run_id}>
            <span className="font-semibold">{r.version !== "general" ? "Earlier method" : i === 0 ? "Latest review" : "Review"}</span>
            {r.finished_at ? ` of ${dateWords(r.finished_at)}` : ""}
            {" "}({r.version !== "general" && r.part ? `${r.part}, ` : ""}{STATUS_WORDS[r.status] ?? r.status.replaceAll("_", " ")}{r.points != null ? `, ${r.points} points` : ""})
          </li>
        ))}
      </ul>
    </section>
  );
}
