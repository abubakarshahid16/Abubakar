/**
 * v2.1 W1 / N2: what is left before signing, in plain words.
 * MUTATION PROOF: push `gate.blockers` unchanged again and the blocker test
 * fails; show the raw error alone and the error test fails.
 */
import { describe, expect, it } from "vitest";

import type { CrsIssueGate, ReviewRunSummary } from "../../../types/api";
import { GATE_READ_FAILED, gateReadError, plainBlocker, signLeft } from "./issueGate";

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
