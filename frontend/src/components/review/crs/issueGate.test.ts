/**
 * v2.1 W1 / N2: what is left before signing, in plain words.
 * MUTATION PROOF: push `gate.blockers` unchanged again and the blocker test
 * fails; show the raw error alone and the error test fails.
 */
import { describe, expect, it } from "vitest";

import type { CrsIssueGate, ReviewRunSummary } from "../../../types/api";
import { GATE_READ_FAILED, OTHER_ITEMS_SHOWN, gateReadError, otherItemCounts, otherItemLines, plainBlocker, signLeft } from "./issueGate";

const run = { review_run_id: "run-1", engineer_final_code: "Code 2" } as unknown as ReviewRunSummary;

function gate(over: Partial<CrsIssueGate> = {}): CrsIssueGate {
  return {
    unread_pages: [], checked_pages: [], pages_total: 4, open_findings: [], blockers: [], issuable: true, final_code_recorded: true,
    ...over,
  } as CrsIssueGate;
}

describe("issueGate words (v2.1)", () => {
  it("the no-page-record blocker is said in plain words", () => {
    const left = signLeft({ gate: gate({
      issuable: false, pages_total: null,
      blockers: ["no page coverage is recorded for this run, so no page can be called read"],
    }) }, run, []);
    expect(left).toEqual(["the record of which pages were read is missing for this review, so no page can be called read yet"]);
    expect(left.join(" ")).not.toMatch(/\brun\b|coverage/);
  });

  it("another blocker passes as the server wrote it", () => {
    expect(plainBlocker("2 finding(s) on the sheet have no engineer's decision")).toBe("2 finding(s) on the sheet have no engineer's decision");
  });

  it("a failed read is a plain sentence, the server's words only as a detail", () => {
    expect(gateReadError("HTTP 502")).toBe(`${GATE_READ_FAILED} Details: HTTP 502`);
    expect(gateReadError("")).toBe(GATE_READ_FAILED);
    expect(gateReadError(undefined)).toBe(GATE_READ_FAILED);
  });

  it("names no internal term", () => {
    expect(signLeft({ gate: null }, run, [])).toEqual(["what is left could not be checked"]);
  });
});

describe("the other items on the issued copy (order 152.2)", () => {
  const item = (id: string, kind: string | null, standard?: string | null) =>
    ({ finding_id: id, row_kind: kind, item: 1, ...(standard === undefined ? {} : { standard }) });

  it("signLeft counts the other items per kind and says where they are", () => {
    const left = signLeft({ gate: gate({ open_findings: [
      item("a", "standard_not_cited"), item("b", "standard_not_cited"), item("c", "missing_reference"),
    ] }) }, run, []);
    expect(left).toEqual(["decide 3 other items on the issued copy (2 standards not cited, 1 not in the library)"]);
  });

  it("each line names the standard when the server sent one, the kind alone when not", () => {
    const { lines } = otherItemLines([
      item("a", "standard_not_cited", "STD-Q 7 clause 2"), item("b", "standard_not_cited", null), item("c", "standard_not_cited", "  "),
    ]);
    expect(lines.map((l) => l.text)).toEqual([
      "a standard the datasheet does not cite: STD-Q 7 clause 2",
      "a standard the datasheet does not cite",
      "a standard the datasheet does not cite",
    ]);
  });

  it("'not in the library' is said only of a missing_reference item", () => {
    const kinds = ["standard_not_cited", "standard_not_applicable", "pages_not_readable", "page_reader_only", "zzz_new_kind", null];
    for (const kind of kinds) {
      expect(otherItemLines([item("a", kind, "STD-Q 7")]).lines[0].text).not.toMatch(/not in the library/);
      expect(otherItemCounts([item("a", kind)])).not.toMatch(/not in the library/);
    }
    expect(otherItemLines([item("a", "missing_reference")]).lines[0].text).toBe("a standard that is not in the library");
  });

  it("a kind it does not know is said so, never guessed", () => {
    expect(otherItemLines([item("a", "zzz_new_kind")]).lines[0].text).toBe("an item on the issued copy that we could not identify");
    expect(otherItemLines([item("a", null)]).lines[0].text).toBe("an item on the issued copy that we could not identify");
    expect(otherItemCounts([item("a", "zzz_new_kind")])).toBe("1 we could not identify");
  });

  it("the list stops at ten lines and counts the rest", () => {
    const many = Array.from({ length: OTHER_ITEMS_SHOWN + 3 }, (_, i) => item(`f${i}`, "standard_not_cited", `STD-Q ${i}`));
    const shown = otherItemLines(many);
    expect(shown.lines).toHaveLength(10);
    expect(shown.more).toBe(3);
    expect(shown.total).toBe(13);
    expect(otherItemLines(many.slice(0, 10)).more).toBe(0);
    expect(shown.moreKinds).toBe("3 standards not cited");
    expect(otherItemLines(many.slice(0, 10)).moreKinds).toBe("");
  });
});
