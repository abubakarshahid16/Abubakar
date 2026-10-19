/**
 * v2.1 round 2: the question about a draft found when the review opened
 * (useCrsDecisions keeps decisions not saved yet in this browser tab).
 *
 * The draft never comes back, or saves, by itself: "N decisions you had not
 * saved were found. Bring them back?" Yes puts them on screen (they then
 * save as any decision does); Discard throws them away. After Yes the line
 * says how many came back, and how many did not because their comment
 * changed on the record, or left the sheet, since. Nothing shows on a
 * signed review (the hook offers no draft there).
 */
import { useState } from "react";

import type { CrsDecisions } from "../../crs/useCrsDecisions";

const LINK = "text-signal-300 underline-offset-2 hover:underline";

function decisionsWord(n: number): string {
  return `${n.toLocaleString()} ${n === 1 ? "decision" : "decisions"}`;
}

export function RestoreDraftLine({ decisions }: { decisions: CrsDecisions }) {
  const [hidden, setHidden] = useState(false);
  const pending = decisions.pendingRestore ?? null;
  const restored = decisions.restored ?? 0;
  const dropped = decisions.restoreDropped ?? 0;

  if (pending && pending.count > 0) {
    return (
      <p role="status" data-testid="ws-restored" data-state="asking"
        className="flex flex-wrap items-center gap-2 text-sm text-slateish-300">
        <span>
          {decisionsWord(pending.count)} you had not saved {pending.count === 1 ? "was" : "were"} found. Bring{" "}
          {pending.count === 1 ? "it" : "them"} back?
        </span>
        <button type="button" onClick={() => decisions.restoreDraft?.()} className={LINK}>Yes</button>
        <button type="button" onClick={() => decisions.discardDraft?.()} className={LINK}>Discard</button>
      </p>
    );
  }
  if (hidden || (restored === 0 && dropped === 0)) return null;
  return (
    <p role="status" data-testid="ws-restored" data-state="done"
      className="flex flex-wrap items-center gap-2 text-sm text-slateish-300">
      <span>
        {restored > 0 && <>{decisionsWord(restored)} you had not saved {restored === 1 ? "was" : "were"} brought back.</>}
        {restored > 0 && dropped > 0 && " "}
        {dropped > 0 && (
          <>
            {decisionsWord(dropped)} {dropped === 1 ? "was" : "were"} not brought back, because{" "}
            {dropped === 1 ? "its comment" : "their comments"} changed since, or {dropped === 1 ? "is" : "are"} no longer on the sheet.
            Decide {dropped === 1 ? "it" : "them"} again.
          </>
        )}
      </span>
      <button type="button" onClick={() => setHidden(true)} className={LINK}>Hide</button>
    </p>
  );
}
