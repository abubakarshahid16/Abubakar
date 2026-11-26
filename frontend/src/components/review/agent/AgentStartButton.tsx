/**
 * Starts an AI review of the open document. Shown ONLY when the one switch is
 * on (`status.enabled`); when the Claude lane is closed it is disabled and
 * says why in plain words. Nothing is drawn while the switch is off.
 */
import { useState } from "react";

import type { AgentStatus } from "../../../types/api";
import { StartReviewStep } from "../panels/StartReviewStep";
import { Button } from "../../kit/Kit";

export const LANE_CLOSED_REASON =
  "The AI reviewer cannot start: the Claude connection is not open on this machine. An administrator opens it in the settings file.";

/** THE ONE START: the button opens the pre-start step (engine, what will leave this Mac, the list, the cost); its Start begins. */
export function AgentStartButton({ status, documentId, filename = null, paperKind = null, onStarted }: {
  status: AgentStatus | null;
  /** The paper's kind when the screen knows it; null when not known. */
  paperKind?: string | null;
  documentId: string;
  filename?: string | null;
  onStarted: (runId: string) => void;
}) {
  const [step, setStep] = useState(false);
  if (!status || !status.enabled) return null;
  // Datasheets only: a paper known to be of another kind gets no button.
  if (paperKind != null && paperKind !== "datasheet") return null;
  const closed = !status.claude_lane_open;

  return (
    <span className="inline-flex flex-col items-start gap-1" data-testid="agent-start">
      <Button variant="secondary" size="sm"
        onClick={() => setStep(true)} disabled={closed || step}
        aria-describedby={closed ? "agent-start-reason" : undefined}
      >
        Start AI review
      </Button>
      {closed && <span id="agent-start-reason" className="text-xs text-slateish-400">{LANE_CLOSED_REASON}</span>}
      {step && (
        <span className="block w-full max-w-xl text-left">
          <StartReviewStep documentId={documentId} filename={filename} onCancel={() => setStep(false)}
            onStarted={(runId) => { setStep(false); onStarted(runId); }} />
        </span>
      )}
    </span>
  );
}
