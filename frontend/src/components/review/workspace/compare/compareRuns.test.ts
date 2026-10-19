/**
 * Builder E (v2.2): matching comments between two reviews. Made-up data.
 *
 * MUTATION PROOF (checked by hand once): match by finding id instead of
 * `findingIdentity` and "matches by requirement although ids differ" fails;
 * drop pass 2 and "falls back to the comment text" fails; drop the
 * `commentLines` filter and "leaves out lines that met the standard" fails.
 */
import { describe, expect, it } from "vitest";

import type { ReviewFinding } from "../../../../types/api";
import type { CrsRow } from "../../crs/crsRows";
import { compareRuns, comparisonLines, findingIdentity, reviewDay } from "./compareRuns";

function finding(over: Partial<ReviewFinding> = {}): ReviewFinding {
  return {
    id: "f", document_id: "d", requirement: "", finding: "", required_action: "", standard_document_id: "std-1",
    requirement_id: null, equipment_tag: null, matched_phrase: null,
    ...over,
  } as ReviewFinding;
}

function line(key: string, over: Partial<ReviewFinding> = {}, text = "", tier: "A" | "B" | "C" = "B"): CrsRow {
  return {
    key, findings: [finding({ id: key, ...over })], tier: { tier, label: tier === "A" ? "Met" : "Comment", reason: null },
    commentNo: null, pageOrSection: "", item: "", clauseAndStandard: "", observation: text, requiredAction: "",
    status: "Open", priorState: "open", tick: false, page: null,
  } as CrsRow;
}

describe("compareRuns", () => {
  it("matches by requirement although finding ids differ, and sorts into three lists", () => {
    const earlier = [
      line("e1", { requirement_id: "r-1", matched_phrase: "Design pressure" }, "Pressure is too low"),
      line("e2", { requirement_id: "r-2" }, "Old wording about material"),
    ];
    const current = [
      line("c1", { requirement_id: "r-1", matched_phrase: "design  pressure" }, "Pressure is below the minimum"),
      line("c3", { requirement_id: "r-3" }, "Noise level is missing"),
    ];
    const got = compareRuns(current, earlier);
    expect(got.still.map((r) => r.key)).toEqual(["c1"]);
    expect(got.added.map((r) => r.key)).toEqual(["c3"]);
    expect(got.gone.map((r) => r.key)).toEqual(["e2"]);
  });

  it("does not match the same requirement on a different item or standard", () => {
    const earlier = [line("e1", { requirement_id: "r-1", matched_phrase: "Inlet" }, "a")];
    const current = [
      line("c1", { requirement_id: "r-1", matched_phrase: "Outlet" }, "b"),
      line("c2", { requirement_id: "r-1", matched_phrase: "Inlet", standard_document_id: "std-2" }, "c"),
    ];
    const got = compareRuns(current, earlier);
    expect(got.still).toEqual([]);
    expect(got.added).toHaveLength(2);
    expect(got.gone).toHaveLength(1);
  });

  it("falls back to the comment text, ignoring case, spaces and punctuation", () => {
    const earlier = [line("e1", {}, "Motor rating: not stated."), line("e2", {}, "Something else")];
    const current = [line("c1", {}, "motor   rating not stated")];
    const got = compareRuns(current, earlier);
    expect(got.still.map((r) => r.key)).toEqual(["c1"]);
    expect(got.gone.map((r) => r.key)).toEqual(["e2"]);
    expect(got.added).toEqual([]);
  });

  it("matches each earlier line at most once", () => {
    const earlier = [line("e1", {}, "Same words")];
    const current = [line("c1", {}, "Same words"), line("c2", {}, "Same words")];
    const got = compareRuns(current, earlier);
    expect(got.still.map((r) => r.key)).toEqual(["c1"]);
    expect(got.added.map((r) => r.key)).toEqual(["c2"]);
  });

  it("leaves out lines that met the standard", () => {
    const got = compareRuns([line("c1", {}, "x", "A")], [line("e1", {}, "y", "A")]);
    expect(got).toEqual({ added: [], gone: [], still: [] });
  });

  it("two empty reviews give three empty lists", () => {
    expect(compareRuns([], [])).toEqual({ added: [], gone: [], still: [] });
  });

  it("a finding with no requirement has no identity", () => {
    expect(findingIdentity(finding())).toBeNull();
    expect(findingIdentity(finding({ requirement_id: "r" }))).toContain("r");
  });
});

describe("comparisonLines", () => {
  it("says each count with its boundary, singular and plural", () => {
    const c = { added: [line("a")], gone: [], still: [line("b"), line("c")] };
    const at = "2026-10-12T08:00:00Z";
    expect(reviewDay(at)).toBe("12 Oct 2026");
    expect(comparisonLines(c, at)).toEqual({
      added: "1 new comment since the review of 12 Oct 2026",
      gone: "0 comments gone since the review of 12 Oct 2026",
      still: "2 comments still open from the review of 12 Oct 2026",
    });
    expect(comparisonLines(c, null).added).toBe("1 new comment since the earlier review");
  });
});
