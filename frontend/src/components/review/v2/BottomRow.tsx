/** SPEC 11: the bottom row: "CRS for your team", "CRS for the contractor" and "Sign and issue", which is GREYED until every point is
 *  decided and the review code is recorded, with the reason in one line. The server refuses too; this only says it first. */
import { useState } from "react";

import { downloadAgentCrs } from "../agent/downloadAgentCrs";
import { downloadCrs } from "../downloadCrs";
import { signWaits } from "./words";

export function BottomRow({ ruleCheckRun, aiRun, undecided, codeRecorded, blockers, signed, onSign }: {
  ruleCheckRun: string | null; aiRun: string | null; undecided: number; codeRecorded: boolean; blockers: string[]; signed: boolean; onSign: () => void;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  const waits = signWaits({ undecided, codeRecorded, blockers });
  async function copy(which: "team" | "contractor") {
    setProblem(null);
    const errors: (string | null)[] = [];
    // The rule check's contractor copy is made only when you sign and issue (the app's one issuing path), so only the team copy is
    // downloaded for it here.
    if (ruleCheckRun && which === "team") errors.push(await downloadCrs(ruleCheckRun, "internal"));
    if (aiRun) errors.push(await downloadAgentCrs(aiRun, which === "team" ? "internal" : "contractor"));
    const bad = errors.find((e) => e);
    if (bad) setProblem(bad);
  }
  const btn = "rounded-[var(--radius-sm)] border border-ink-500 px-3 py-1.5 text-sm text-slateish-100 hover:bg-ink-700";
  return (
    <section data-testid="v2-bottom" aria-label="Copies and signing" className="space-y-2 border-t border-ink-600 pt-3">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className={btn} onClick={() => void copy("team")}>CRS for your team</button>
        <button type="button" className={btn} onClick={() => void copy("contractor")} disabled={!aiRun}
          title={aiRun ? undefined : "The contractor file is made when you sign and issue"}>CRS for the contractor</button>
        <button type="button" onClick={onSign} disabled={signed || waits != null} data-testid="v2-sign"
          className="ml-auto rounded-[var(--radius-sm)] bg-signal-500 px-4 py-1.5 text-sm font-semibold text-ink-950 disabled:cursor-not-allowed disabled:bg-ink-600 disabled:text-slateish-500">
          {signed ? "Signed" : "Sign and issue"}
        </button>
      </div>
      <p className="text-xs text-slateish-400" data-testid="v2-contractor-line">
        The contractor file holds only what code proved, or your own words. It never carries an AI wording. The rule check's contractor file is made when you sign and issue.
      </p>
      {waits && !signed && <p role="status" data-testid="v2-sign-waits" className="text-xs text-slateish-300">{waits}</p>}
      {problem && <p role="alert" className="text-xs text-danger-500">{problem}</p>}
    </section>
  );
}
