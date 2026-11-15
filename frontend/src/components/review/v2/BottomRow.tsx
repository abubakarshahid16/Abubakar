/** SPEC 11: the bottom row: "CRS for your team", "CRS for the contractor" and "Sign and issue", which is GREYED until every point is
 *  decided and the review code is recorded, with the reason in one line. The server refuses too; this only says it first. */
import { useState } from "react";

import { downloadPaperCrs } from "../agent/downloadAgentCrs";
import { signWaits } from "./words";

export function BottomRow({ documentId, undecided, codeRecorded, blockers, signed, onSign }: {
  documentId: string | null; undecided: number; codeRecorded: boolean; blockers: string[]; signed: boolean; onSign: () => void;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  const waits = signWaits({ undecided, codeRecorded, blockers });
  async function copy(which: "team" | "contractor") {
    setProblem(null);
    // ONE file per button (K4): every point the page counts, drawn from the page's own list. After signing, the contractor file is the
    // issued one, byte for byte. The older per-run files are under "How it was reviewed".
    if (!documentId) return;
    const bad = await downloadPaperCrs(documentId, which);
    if (bad) setProblem(bad);
  }
  const btn = "rounded-[var(--radius-sm)] border border-ink-500 px-3 py-1.5 text-sm text-slateish-100 hover:bg-ink-700";
  return (
    <section data-testid="v2-bottom" aria-label="Copies and signing" className="space-y-2 border-t border-ink-600 pt-3">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className={btn} onClick={() => void copy("team")}>CRS for your team</button>
        <button type="button" className={btn} onClick={() => void copy("contractor")} disabled={!documentId}>
          {signed ? "CRS for the contractor (working copy)" : "CRS for the contractor (working copy, not issued)"}
        </button>
        <button type="button" onClick={onSign} disabled={signed || waits != null} data-testid="v2-sign"
          className="ml-auto rounded-[var(--radius-sm)] bg-signal-500 px-4 py-1.5 text-sm font-semibold text-ink-950 disabled:cursor-not-allowed disabled:bg-ink-600 disabled:text-slateish-500">
          {signed ? "Signed" : "Sign and issue"}
        </button>
      </div>
      <p className="text-xs text-slateish-400" data-testid="v2-contractor-line">
        The contractor file holds the failures code proved that you kept, and the points whose words are yours (edited or written by you). A kept point with no words of yours is not issued. It is a working copy until you sign and issue.
      </p>
      {waits && !signed && <p role="status" data-testid="v2-sign-waits" className="text-xs text-slateish-300">{waits}</p>}
      {problem && <p role="alert" className="text-xs text-danger-500">{problem}</p>}
    </section>
  );
}
