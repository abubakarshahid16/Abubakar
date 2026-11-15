/** The older files, one per run, stay reachable here (K4): the page's two buttons download the ONE file of the paper. */
import { useState } from "react";

import { downloadAgentCrs } from "../agent/downloadAgentCrs";
import { downloadCrs } from "../downloadCrs";

export function OlderFiles({ ruleCheckRun, aiRun }: { ruleCheckRun: string | null; aiRun: string | null }) {
  const [problem, setProblem] = useState<string | null>(null);
  if (!ruleCheckRun && !aiRun) return null;
  const btn = "rounded-[var(--radius-sm)] border border-ink-500 px-3 py-1 text-xs text-slateish-100 hover:bg-ink-700";
  async function get(run: () => Promise<string | null>) {
    setProblem(null);
    const bad = await run();
    if (bad) setProblem(bad);
  }
  return (
    <section data-testid="v2-older-files" aria-label="Older files" className="mt-3 space-y-2 rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-3">
      <h3 className="text-sm font-semibold text-slateish-100">Older files, one per review</h3>
      <p className="text-xs text-slateish-400">The buttons at the bottom give one file with every point on this page. These are the files of each single review, as before.</p>
      <div className="flex flex-wrap gap-2">
        {ruleCheckRun && <button type="button" className={btn} onClick={() => void get(() => downloadCrs(ruleCheckRun, "internal"))}>Rule check, internal copy</button>}
        {aiRun && <button type="button" className={btn} onClick={() => void get(() => downloadAgentCrs(aiRun, "internal"))}>AI review, internal copy</button>}
        {aiRun && <button type="button" className={btn} onClick={() => void get(() => downloadAgentCrs(aiRun, "contractor"))}>AI review, contractor working copy (older file, not the issued one)</button>}
      </div>
      {problem && <p role="alert" className="text-xs text-danger-500">{problem}</p>}
    </section>
  );
}
