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

/** A stored stop reason is "<code>: <sentence>": the screen shows the sentence only (the code stays in the stored reason). */
export function plainStop(reason: string): string {
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
