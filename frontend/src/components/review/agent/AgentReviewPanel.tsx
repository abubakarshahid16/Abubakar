/**
 * The "AI review" tab of one review: summary, the two CRS downloads, the
 * lines, and the trace of a chosen line. A review that was not made by the AI
 * reviewer says so plainly (the summary route answers 404 for it).
 */
import { useEffect, useState } from "react";

import { agentReview, isFeatureOff } from "../../../api/agentReview";
import type { AgentRunSummary } from "../../../types/api";
import { AgentLines } from "./AgentLines";
import { AgentSummary } from "./AgentSummary";
import { AgentTrace } from "./AgentTrace";
import { downloadAgentCrs } from "./downloadAgentCrs";
import { OlderFileLine } from "./OlderFileLine";
import { CONTRACTOR_CRS_LINE, INTERNAL_CRS_LINE } from "./plainWords";
import { Button } from "../../kit/Kit";

export const NOT_AGENT_RUN = "This review was not made by the AI reviewer, so there is nothing to show here.";

export function AgentReviewPanel({ runId, onOpenRules }: { runId: string; onOpenRules?: () => void }) {
  const [summary, setSummary] = useState<AgentRunSummary | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "none" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setState("loading"); setSummary(null); setTrace(null);
    void agentReview.summary(runId).then((r) => {
      if (!live) return;
      if (r.ok) { setSummary(r.data); setState("ok"); return; }
      if (isFeatureOff(r)) { setState("none"); return; }
      setError(r.error.message); setState("error");
    });
    return () => { live = false; };
  }, [runId]);

  async function download(copy: "internal" | "contractor") {
    setFileError(null);
    const message = await downloadAgentCrs(runId, copy);
    if (message) setFileError(message);
  }

  if (state === "loading") return <p role="status" className="text-sm text-slateish-400">Reading the AI review…</p>;
  if (state === "none") return <p data-testid="agent-not-agent" className="text-sm text-slateish-300">{NOT_AGENT_RUN}</p>;
  if (state === "error" || !summary) return <p role="alert" className="text-sm text-red-400">{error}</p>;
  return (
    <div className="space-y-6" data-testid="agent-review-panel">
      <AgentSummary summary={summary} />
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" onClick={() => void download("internal")}>
          Download CRS, internal copy
        </Button>
        <Button variant="secondary" size="sm" onClick={() => void download("contractor")}>
          Download CRS, contractor copy
        </Button>
        <span className="text-xs text-slateish-400">{INTERNAL_CRS_LINE} {CONTRACTOR_CRS_LINE}</span>
        {onOpenRules && (
          <Button variant="secondary" onClick={onOpenRules} data-testid="agent-open-rules">
            Rules used
          </Button>
        )}
        {fileError && <span role="alert" className="text-xs text-red-400">{fileError}</span>}
      </div>
      <OlderFileLine runId={runId} where="the one CRS of the paper" />
      <AgentLines runId={runId} onOpenTrace={setTrace} mode={summary.mode} />
      {trace && <AgentTrace runId={runId} itemId={trace} onClose={() => setTrace(null)} />}
    </div>
  );
}
