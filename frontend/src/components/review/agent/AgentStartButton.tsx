/**
 * Starts an AI review of the open document. Shown ONLY when the one switch is
 * on (`status.enabled`); when the Claude lane is closed it is disabled and
 * says why in plain words. Nothing is drawn while the switch is off.
 */
import { useState } from "react";

import { agentReview } from "../../../api/agentReview";
import type { AgentStatus, ReviewRunSummary } from "../../../types/api";

export const LANE_CLOSED_REASON =
  "The AI reviewer cannot start: the Claude connection is not open on this machine. An administrator opens it in the settings file.";

export function AgentStartButton({ status, documentId, paperKind = null, onStarted }: {
  status: AgentStatus | null;
  /** The paper's kind when the screen knows it; null when not known. */
  paperKind?: string | null;
  documentId: string;
  onStarted: (run: ReviewRunSummary) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!status || !status.enabled) return null;
  // Datasheets only: a paper known to be of another kind gets no button.
  if (paperKind != null && paperKind !== "datasheet") return null;
  const closed = !status.claude_lane_open;

  async function press() {
    setBusy(true);
    setError(null);
    const result = await agentReview.start(documentId);
    setBusy(false);
    // 409 "kind_not_enabled": the server's own words, plainly, nothing else.
    if (!result.ok) setError(result.error.message);
    else onStarted(result.data);
  }

  return (
    <span className="inline-flex flex-col items-start gap-1" data-testid="agent-start">
      <button
        type="button" onClick={() => void press()} disabled={closed || busy}
        aria-describedby={closed ? "agent-start-reason" : undefined}
        className="rounded-[var(--radius-sm)] border border-signal-300 px-3 py-1.5 text-sm font-semibold text-signal-300 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {busy ? "Starting…" : "Start AI review"}
      </button>
      {closed && <span id="agent-start-reason" className="text-xs text-slateish-400">{LANE_CLOSED_REASON}</span>}
      {error && <span role="alert" className="text-xs text-red-400">{error}</span>}
    </span>
  );
}
