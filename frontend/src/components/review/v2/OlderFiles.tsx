/** The older files, one per run, stay reachable here (K4): the page's two buttons download the ONE file of the paper. */
import { useEffect, useState } from "react";

import { request } from "../../../api/core";
import { downloadAgentCrs } from "../agent/downloadAgentCrs";
import { OlderFileLine } from "../agent/OlderFileLine";
import { downloadCrs } from "../downloadCrs";
import { useOldCrsDownload } from "./usePoints";
import { EARLIER_VERSION } from "./words";

/** One review of the paper, from GET /api/reviews/papers/{id}/history (piece D). `points` is null where the run stores no count. */
export type HistoryRun = {
  run_id: string;
  version: "general" | "earlier version";
  part: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  points: number | null;
  files: { label: string; url: string }[];
};
export type PaperHistory = { paper_document_id: string; boundary: string; runs: HistoryRun[] };

// The one word for an older review lives in words.ts (one home); re-exported for the callers that import it from here.
export { EARLIER_VERSION };

const isHistory = (b: unknown): boolean => typeof b === "object" && b !== null && Array.isArray((b as { runs?: unknown }).runs);

/** The paper's history, read once. Null while unknown or unreadable (the older buttons stay as they are). */
export function usePaperHistory(documentId: string | null | undefined): PaperHistory | null {
  const [history, setHistory] = useState<PaperHistory | null>(null);
  useEffect(() => {
    if (!documentId) return;
    let live = true;
    void request<PaperHistory>(`/reviews/papers/${encodeURIComponent(documentId)}/history`, undefined, isHistory).then((r) => {
      if (live && r.ok) setHistory(r.data);
    });
    return () => { live = false; };
  }, [documentId]);
  return history;
}

/** The download an earlier review's file link stands for: its own, unchanged route, with the session (a link cannot send the header). */
function earlierDownload(run: HistoryRun, url: string): (() => Promise<string | null>) | null {
  if (run.version !== "earlier version") return null;
  const copy = new URL(url, "http://local").searchParams.get("copy");
  if (run.part === "AI review") return () => downloadAgentCrs(run.run_id, copy === "contractor" ? "contractor" : "internal");
  if (run.part === "rule check") return () => downloadCrs(run.run_id, "internal");
  return null;
}

function when(value: string | null): string {
  return value ? value.slice(0, 16).replace("T", " ") : "";
}

/** Every review of the paper, newest first. An older one says "Earlier version" and keeps its own file buttons. */
export function PaperHistoryList({ history, onProblem }: { history: PaperHistory; onProblem: (message: string | null) => void }) {
  const btn = "rounded-[var(--radius-sm)] border border-ink-500 px-3 py-1 text-xs text-slateish-100 hover:bg-ink-700";
  if (history.runs.length === 0) return null;
  return (
    <div data-testid="paper-history" className="space-y-1">
      <p className="text-xs text-slateish-400">Every review of this paper ({history.boundary}), newest first.</p>
      <ul className="space-y-1">
        {history.runs.map((run) => (
          <li key={run.run_id} data-testid="history-run" className="flex flex-wrap items-center gap-2 text-xs text-slateish-100">
            <span className="font-semibold">{run.version === "earlier version" ? EARLIER_VERSION : "General review"}</span>
            <span>{run.part}</span>
            <span className="text-slateish-400">{run.status}{when(run.started_at) ? `, ${when(run.started_at)}` : ""}</span>
            {run.points !== null && <span className="text-slateish-400">{run.points} points</span>}
            {run.files.map((f) => {
              const go = earlierDownload(run, f.url);
              if (!go) return null;
              return (
                <button key={f.url} type="button" className={btn} onClick={() => { onProblem(null); void go().then((bad) => { if (bad) onProblem(bad); }); }}>
                  {EARLIER_VERSION}: {f.label}
                </button>
              );
            })}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function OlderFiles({ ruleCheckRun, aiRun, documentId }: { ruleCheckRun: string | null; aiRun: string | null; documentId?: string | null }) {
  const history = usePaperHistory(documentId);
  const [problem, setProblem] = useState<string | null>(null);
  // Owner order, 16 Nov 2026: these files do not state their counts; switched off, only the paper's one CRS is offered.
  const offered = useOldCrsDownload();
  if (!offered || (!ruleCheckRun && !aiRun && !(history && history.runs.length > 0))) return null;
  const btn = "rounded-[var(--radius-sm)] border border-ink-500 px-3 py-1 text-xs text-slateish-100 hover:bg-ink-700";
  async function get(run: () => Promise<string | null>) {
    setProblem(null);
    const bad = await run();
    if (bad) setProblem(bad);
  }
  return (
    <details data-testid="v2-older-files" aria-label="Older files" className="mt-3 space-y-2 rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-3">
      <summary className="cursor-pointer text-sm font-semibold text-slateish-100">History: older files, one per review ({EARLIER_VERSION})</summary>
      <p data-testid="earlier-version-note" className="text-xs text-slateish-400">{EARLIER_VERSION}: these files come from the rule check and the earlier AI review, not from the general review. The buttons at the bottom give one file with every point on this page. These are the files of each single review, as before.</p>
      <div className="flex flex-wrap gap-2">
        {ruleCheckRun && <button type="button" className={btn} onClick={() => void get(() => downloadCrs(ruleCheckRun, "internal"))}>Rule check, internal copy</button>}
        {aiRun && <button type="button" className={btn} onClick={() => void get(() => downloadAgentCrs(aiRun, "internal"))}>AI review, internal copy</button>}
        {aiRun && <button type="button" className={btn} onClick={() => void get(() => downloadAgentCrs(aiRun, "contractor"))}>AI review, contractor working copy (older file, not the issued one)</button>}
      </div>
      {aiRun && <OlderFileLine runId={aiRun} />}
      {history && <PaperHistoryList history={history} onProblem={setProblem} />}
      {problem && <p role="alert" className="text-xs text-danger-500">{problem}</p>}
    </details>
  );
}
