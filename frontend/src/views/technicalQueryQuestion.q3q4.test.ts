/** H's review of the owner's real file (27 Nov 2026): Q3, a reply citing 0 sources offered to reject all 12; Q4, "Reply written" was ticked
 *  for a reply to an earlier wording. Invented values. */
import { describe, expect, it } from "vitest";

import { citedSplit, querySteps } from "./technicalQueryQuestion";

const src = (id: string, state = "proposed") => ({ id, evidence_state: state, supersession_state: "unknown", for_current_question: true });
const twelve = Array.from({ length: 12 }, (_, i) => src(`e${i}`));

describe("keep the cited, reject the others (Q3)", () => {
  it("rejects nothing when the reply cites no source", () => {
    expect(citedSplit(twelve, "[]")).toEqual({ keep: [], reject: [], citesNone: true });
    expect(citedSplit(twelve, null)).toEqual({ keep: [], reject: [], citesNone: true });
  });

  it("rejects nothing when the reply cites only sources of an earlier search", () => {
    const old = [...twelve, { ...src("old1"), for_current_question: false }];
    expect(citedSplit(old, JSON.stringify([{ evidence_id: "old1" }]))).toEqual({ keep: [], reject: [], citesNone: true });
  });

  it("keeps the cited and rejects the others when the reply does cite this question's sources", () => {
    const split = citedSplit(twelve, JSON.stringify([{ evidence_id: "e3" }]));
    expect(split.citesNone).toBe(false);
    expect(split.keep.map((e) => e.id)).toEqual(["e3"]);
    expect(split.reject).toHaveLength(11);
  });
});

describe("the Reply written step (Q4)", () => {
  const base = { status: "awaiting_review", drafts: [{}], evidence: twelve };
  it("is done only when the reply answers the current question", () => {
    expect(querySteps({ ...base, ready: { evidence: "ready", draft: "ready", draft_fresh: true } }, "Q?")[2].state).toBe("done");
    expect(querySteps({ ...base, ready: { evidence: "ready", draft: "ready", draft_fresh: false } }, "Q?")[2].state).toBe("stale");
    expect(querySteps({ ...base, drafts: [], ready: null }, "Q?")[2].state).toBe("todo");
  });
});
