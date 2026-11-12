/**
 * One read of an AI review for the page's top panel, the steps headline and
 * the signing guard: its summary and ALL its lines (page by page). Nothing is
 * drawn from it unless the summary says the run has an AI review. If the
 * lines cannot be read in full, `lines` is null and every number that needs
 * them is null (shown as nothing, never 0); the guard then treats the open
 * points as not known.
 */
import { useEffect, useState } from "react";

import { agentReview, isFeatureOff } from "../../../api/agentReview";
import type { AgentLine, AgentRunSummary } from "../../../types/api";
import { type MissingSplit, missingSplit, openPoints } from "./plainWords";

export type AgentOverview =
  | { state: "off" }
  | { state: "loading" }
  | { state: "none" }
  | { state: "error"; message: string }
  | { state: "ok"; summary: AgentRunSummary; lines: AgentLine[] | null; openPoints: number | null; missing?: MissingSplit | null };

const MAX_PAGES = 200;

/** `enabled` false (the switch is off, or the run is not finished): nothing is read. */
export function useAgentOverview(runId: string, enabled: boolean): AgentOverview {
  const [view, setView] = useState<AgentOverview>(enabled ? { state: "loading" } : { state: "off" });
  useEffect(() => {
    if (!enabled) { setView({ state: "off" }); return undefined; }
    let live = true;
    setView({ state: "loading" });
    void (async () => {
      const summary = await agentReview.summary(runId);
      if (!live) return;
      if (!summary.ok) {
        setView(isFeatureOff(summary) ? { state: "none" } : { state: "error", message: summary.error.message });
        return;
      }
      // The two kinds of missing rule book, apart; unknown (null) when the rules-used record cannot be read.
      const rules = await agentReview.rulesUsed(runId);
      if (!live) return;
      const missing = rules.ok ? missingSplit(rules.data.missing_books) : null;
      const lines: AgentLine[] = [];
      let cursor: string | null = null;
      let complete = false;
      for (let page = 0; page < MAX_PAGES; page += 1) {
        const got = await agentReview.lines(runId, cursor);
        if (!live) return;
        if (!got.ok) break;
        lines.push(...got.data.lines);
        cursor = got.data.next ?? null;
        if (!cursor) { complete = true; break; }
      }
      setView({
        state: "ok", summary: summary.data,
        lines: complete ? lines : null, openPoints: complete ? openPoints(lines) : null, missing,
      });
    })();
    return () => { live = false; };
  }, [runId, enabled]);
  return view;
}
