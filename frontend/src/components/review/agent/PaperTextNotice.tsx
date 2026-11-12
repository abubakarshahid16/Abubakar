/**
 * What the library holds for the paper to read. A paper with no stored text (or with text that is not indexed) is
 * refused before any rule is asked: this says so in one plain sentence. A partly readable paper is reviewed, and the
 * pages with no stored text are listed as not read. A readable paper, or a run stored before this was kept, shows nothing.
 */
import type { AgentPaperText } from "../../../types/api";

export const STOPS = ["no text", "not indexed", "still reading"] as const;

/** True when the review was refused for lack of readable text. */
export function paperTextStopped(p: AgentPaperText | null | undefined): boolean {
  return p != null && (STOPS as readonly string[]).includes(p.state);
}

const BARE_CODE_WORDS: Record<string, string> = {
  paper_kind_unknown: "The paper kind is unknown, so no rule was asked.",
  kind_not_enabled: "The AI review is not enabled for this kind of paper, so no rule was asked.",
  gate_closed: "The Claude lane is closed, so the AI could not be asked.",
  usd_cap_reached: "The review stopped because a spending cap was reached.",
  app_step_cap: "The review stopped because a spending cap was reached.",
  budget_stop: "The review stopped because a spending cap was reached.",
  run_stopped: "The review was stopped before it finished.",
};
const BARE_FALLBACK = "The review stopped before it finished; no further reason was recorded.";

/** A stored stop reason is "<code>: <sentence>" or a bare "<code>": the screen shows a plain sentence, never the code word. */
export function plainStop(reason: string): string {
  if (/^[a-z][a-z_]*$/.test(reason)) return BARE_CODE_WORDS[reason] ?? BARE_FALLBACK;
  return reason.replace(/^[a-z][a-z_]*: /, "");
}

export function PaperTextNotice({ paperText }: { paperText: AgentPaperText | null | undefined }) {
  if (paperText == null || paperText.state === "readable" || !paperText.sentence) return null;
  if (paperTextStopped(paperText)) {
    return (
      <p role="alert" data-testid="paper-text-stop"
        className="rounded-[var(--radius-sm)] border border-red-500/50 bg-red-500/10 px-3 py-2 text-sm text-slateish-100">
        {paperText.sentence}
      </p>
    );
  }
  return (
    <div role="status" data-testid="paper-text-partly"
      className="rounded-[var(--radius-sm)] border border-warn-500/50 bg-warn-500/10 px-3 py-2 text-sm text-slateish-100">
      <p>{paperText.sentence}</p>
      <p className="text-xs text-slateish-300" data-testid="paper-text-pages">
        Pages not read: {paperText.pages_not_read.join(", ")}
      </p>
    </div>
  );
}
