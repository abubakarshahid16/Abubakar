/**
 * Builder B: the one source of numbers, rule by rule (SPEC.md section 4),
 * on made-up data only.
 */
import { describe, expect, it } from "vitest";

import type { CrsIssueGate, ReviewFinding, ReviewReadiness, ReviewRunSummary, ReviewRunTierSummary } from "../../../types/api";
import type { CrsRow, DecisionState, ReviewNumbersInput } from "./contract";
import { actionSteps, computeReviewNumbers, pagesDetail, verdictLine } from "./numbers";

type Tier = "A" | "B" | "C";
const LABEL: Record<Tier, string> = { A: "Met", B: "Comment", C: "Needs you" };

function row(key: string, tier: Tier, opts: { label?: string; findings?: number; prior?: "open" | "agreed" } = {}): CrsRow {
  const findings = Array.from({ length: opts.findings ?? 1 }, (_, i) => ({ id: `${key}-f${i}` }));
  return {
    key, tier: { tier, label: opts.label ?? LABEL[tier], reason: null }, findings, priorState: opts.prior ?? "open",
  } as unknown as CrsRow;
}

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "Pump datasheet rev B.pdf",
    status: "completed", ...over,
  } as ReviewRunSummary;
}

const NO_DECISIONS: DecisionState = { decisions: {}, opened: {} };

function input(over: Partial<ReviewNumbersInput> = {}): ReviewNumbersInput {
  return {
    run: run(), findings: [], rows: [], summary: null, missingStandards: [], readiness: readiness(),
    decisions: NO_DECISIONS, unsaved: [], gate: null, ...over,
  };
}

/** The issue gate as the server answers it; by default nothing is left. */
function gate(over: Partial<CrsIssueGate> = {}): CrsIssueGate {
  return {
    review_run_id: "run-1", issuable: true, final_code_recorded: true, blockers: [], unread_pages: [], open_findings: [], ...over,
  } as CrsIssueGate;
}

function readiness(over: Partial<ReviewReadiness> = {}): ReviewReadiness {
  return {
    submittal_document_id: "doc-1", pages_total: 12, pages_read: 9, unread_pages: [], unread_page_reasons: {},
    standards_cited: 2, standards_held: [], standards_missing: [], last_run_id: null, nothing_changed: false, changes: [],
    ledger_state: "current", ledger_note: null, ...over,
  };
}

function summary(removed: number, how: Record<string, unknown> = {}): ReviewRunTierSummary {
  return { counts: { removed }, how_reviewed: how } as unknown as ReviewRunTierSummary;
}

const ROWS = [
  row("b1", "B", { findings: 3 }),
  row("c1", "C"),
  row("b2", "B", { prior: "agreed" }),
  row("c2", "C", { findings: 2 }),
  row("a1", "A"),
  row("a2", "A"),
  row("na", "A", { label: "Not applicable" }),
  row("other", "A", { label: "Another document" }),
];

describe("computeReviewNumbers", () => {
  it("counts comment rows (B + C), needs-you rows and the findings behind comments", () => {
    const n = computeReviewNumbers(input({ rows: ROWS }));
    expect(n.comments).toBe(4);
    expect(n.needsYou).toBe(2);
    expect(n.findingsInComments).toBe(3 + 1 + 1 + 2);
    expect(n.met).toBe(2);
    expect(n.anotherDocument).toBe(1);
  });

  it("not applicable: rows and clauses are kept apart", () => {
    // Rows: always the sheet's own not-applicable rows (CrsSheetView's rowCounts).
    const plain = computeReviewNumbers(input({ rows: ROWS }));
    expect(plain.notApplicableRows).toBe(1);
    expect(plain.notApplicableClauses).toBeNull();
    const split = run({ requirement_split: { does_not_apply: 7 } } as Partial<ReviewRunSummary>);
    const withClauses = computeReviewNumbers(input({ rows: ROWS, run: split }));
    expect(withClauses.notApplicableRows).toBe(1);
    expect(withClauses.notApplicableClauses).toBe(7);
    // The server summary's how_reviewed wins over the run row for clauses.
    const s = summary(0, { requirement_split: { does_not_apply: 9 } });
    const fromSummary = computeReviewNumbers(input({ rows: ROWS, summary: s, run: split }));
    expect(fromSummary.notApplicableClauses).toBe(9);
    expect(fromSummary.notApplicableRows).toBe(1);
  });

  it("unread pages: once the issue gate answers, the pages it still wants ticked", () => {
    const r = run({ page_coverage: { pages_not_read_into_fields: [3, 4] } } as Partial<ReviewRunSummary>);
    const n = computeReviewNumbers(input({
      run: r, readiness: readiness({ unread_pages: [3, 4, 9] }),
      gate: gate({ unread_pages: [{ page: 9, reason: null }, { page: 4, reason: "scan" }] } as Partial<CrsIssueGate>),
    }));
    expect(n.unreadPages).toEqual([4, 9]);
    expect(n.pagesKnown).toBe(true);
    // The gate known, readiness not: pages are still known (the gate says them).
    expect(computeReviewNumbers(input({ readiness: null, gate: gate() })).pagesKnown).toBe(true);
  });

  it("unread pages: known from readiness only when its page ledger is current", () => {
    expect(computeReviewNumbers(input({ gate: null })).pagesKnown).toBe(true);
    for (const ledger of ["missing", "stale", "not_as_submittal", undefined] as const) {
      const n = computeReviewNumbers(input({ gate: null, readiness: readiness({ ledger_state: ledger }) }));
      expect(n.pagesKnown, String(ledger)).toBe(false);
      const pages = actionSteps(n).find((s) => s.id === "pages")!;
      expect(pages).toMatchObject({ count: null, done: false, enabled: true, label: "Check unread pages (not known yet)" });
    }
  });

  it("signLeft: the issue gate's remaining items, never empty while the gate is unknown", () => {
    expect(computeReviewNumbers(input()).signLeft).toEqual(["what is left could not be checked"]);
    expect(computeReviewNumbers(input({ gate: gate() })).signLeft).toEqual([]);
    const left = computeReviewNumbers(input({
      gate: gate({ final_code_recorded: false, issuable: false, unread_pages: [{ page: 2, reason: null }] } as Partial<CrsIssueGate>),
    })).signLeft;
    expect(left).toEqual(["record the final code", "tick 1 unread page"]);
    // A code the engineer recorded on the run counts as recorded.
    const recorded = computeReviewNumbers(input({
      run: run({ engineer_final_code: "B" } as Partial<ReviewRunSummary>), gate: gate({ final_code_recorded: false }),
    }));
    expect(recorded.signLeft).toEqual([]);
  });

  it("removed: the summary's count, else the rejected findings (summary null)", () => {
    const findings = [
      { id: "1", approval_status: "rejected" }, { id: "2", approval_status: "pending" }, { id: "3", approval_status: "rejected" },
    ] as ReviewFinding[];
    expect(computeReviewNumbers(input({ findings, summary: null })).removed).toBe(2);
    expect(computeReviewNumbers(input({ findings, summary: summary(5) })).removed).toBe(5);
    expect(computeReviewNumbers(input({ findings, summary: summary(0) })).removed).toBe(0);
  });

  it("unread pages (order 127): the run's one list; readiness adds no page when the run holds it", () => {
    const r = run({ unread_pages: [9, 4], page_coverage: { pages_not_read_into_fields: [9] } } as Partial<ReviewRunSummary>);
    const n = computeReviewNumbers(input({ run: r, readiness: readiness({ unread_pages: [12, 4, 9, 12] }) }));
    expect(n.unreadPages).toEqual([4, 9]);
  });

  it("unread pages: readiness stands in, sorted and unique, only when the run does not hold the list", () => {
    const r = run({ unread_pages: null } as Partial<ReviewRunSummary>);
    expect(computeReviewNumbers(input({ run: r, readiness: readiness({ unread_pages: [12, 4, 12] }) })).unreadPages).toEqual([4, 12]);
    expect(computeReviewNumbers(input({ run: r, readiness: null })).unreadPages).toEqual([]);
  });

  it("unread pages: readiness unknown (null) uses the run's list only", () => {
    const r = run({ unread_pages: [3] } as Partial<ReviewRunSummary>);
    expect(computeReviewNumbers(input({ run: r, readiness: null })).unreadPages).toEqual([3]);
    expect(computeReviewNumbers(input({ readiness: null })).unreadPages).toEqual([]);
  });

  it("unread pages: from the summary's how_reviewed one list when sent, not the code readers' keys", () => {
    const s = summary(0, { unread_pages: [2, 5], page_coverage: { pages_not_read_into_fields: [5] }, timed_out_pages: [9] });
    expect(computeReviewNumbers(input({ summary: s, readiness: readiness({ unread_pages: [7] }) })).unreadPages).toEqual([2, 5]);
  });

  it("missing standards: input and readiness merged, unique, in first-seen order", () => {
    const n = computeReviewNumbers(input({
      missingStandards: ["API 610", "ASME B16.5"], readiness: readiness({ standards_missing: ["ASME B16.5", "ISO 5199"] }),
    }));
    expect(n.missingStandards).toEqual(["API 610", "ASME B16.5", "ISO 5199"]);
    expect(computeReviewNumbers(input({ missingStandards: ["API 610"], readiness: null })).missingStandards).toEqual(["API 610"]);
  });

  it("undecided: comment rows with no decision and not agreed earlier, in row order", () => {
    const decisions: DecisionState = { decisions: { c1: { kind: "keep" } }, opened: { c2: true } };
    const n = computeReviewNumbers(input({ rows: ROWS, decisions }));
    // b2 is agreed already, c1 is decided, a* are not comments.
    expect(n.undecidedKeys).toEqual(["b1", "c2"]);
    expect(n.undecided).toBe(2);
  });

  it("unopened needs-you rows and unsaved decisions", () => {
    const decisions: DecisionState = { decisions: {}, opened: { c2: true, b1: true } };
    const n = computeReviewNumbers(input({ rows: ROWS, decisions, unsaved: ["b1", "c1"] }));
    expect(n.unopenedNeedsYou).toBe(1);
    expect(n.unsaved).toBe(2);
  });

  /** D5. MUTATION PROOF: drop `&& r.priorState !== "agreed"` from
   *  unopenedNeedsYou and this fails. */
  it("a Needs you row decided in an earlier session counts as opened", () => {
    const rows = [row("c-old", "C", { prior: "agreed" }), row("c-new", "C")];
    const n = computeReviewNumbers(input({ rows }));
    expect(n.unopenedNeedsYou).toBe(1);
    expect(computeReviewNumbers(input({ rows, decisions: { decisions: {}, opened: { "c-new": true } } })).unopenedNeedsYou).toBe(0);
  });

  /** D3: the count "Keep all remaining comments" shows is acceptAll's own
   *  rule: ordinary comments, no decision, not answered earlier; never a
   *  Needs you row. */
  it("remainingToKeep: undecided ordinary comments only, never Needs you", () => {
    const decisions: DecisionState = { decisions: { b1: { kind: "keep" } }, opened: {} };
    const rows = [row("b1", "B"), row("b3", "B"), row("b4", "B"), row("b2", "B", { prior: "agreed" }), row("c1", "C"), row("a1", "A")];
    expect(computeReviewNumbers(input({ rows, decisions })).remainingToKeep).toBe(2);
    expect(computeReviewNumbers(input({ rows: [row("c1", "C")] })).remainingToKeep).toBe(0);
  });

  it("signed from crs_issued_at", () => {
    expect(computeReviewNumbers(input()).signed).toBe(false);
    expect(computeReviewNumbers(input()).signedAt).toBeNull();
    const n = computeReviewNumbers(input({ run: run({ crs_issued_at: "2026-10-19T10:00:00" }) }));
    expect(n.signed).toBe(true);
    expect(n.signedAt).toBe("2026-10-19T10:00:00");
  });

  it("is pure: the same input gives the same answer and is not changed", () => {
    const i = input({ rows: ROWS, readiness: readiness({ unread_pages: [3, 1] }) });
    const before = JSON.stringify(i);
    expect(computeReviewNumbers(i)).toEqual(computeReviewNumbers(i));
    expect(JSON.stringify(i)).toBe(before);
  });
});

describe("actionSteps", () => {
  const busy = computeReviewNumbers(input({
    rows: ROWS, missingStandards: ["API 610", "ISO 5199"], readiness: readiness({ unread_pages: [4, 9, 12] }),
  }));
  const step = (steps: ReturnType<typeof actionSteps>, id: string) => steps.find((s) => s.id === id)!;

  it("gives the five steps in fixed order with their counts; the final code is a step before Sign (S1)", () => {
    const steps = actionSteps(busy);
    expect(steps.map((s) => s.id)).toEqual(["standards", "pages", "decide", "code", "sign"]);
    expect(steps.map((s) => s.label)).toEqual([
      "Upload missing standards (2)", "Check unread pages (3)", "Decide comments (3)",
      "Record the final code (not known yet)", "Sign and export",
    ]);
    expect(steps[1].detail).toBe("Pages 4, 9 and 12");
    expect(step(steps, "sign").enabled).toBe(false);
    expect(steps.slice(0, 4).every((s) => s.enabled && !s.done)).toBe(true);
  });

  it("the final code step: open while the gate says no code, done with the code once recorded", () => {
    const noCode = computeReviewNumbers(input({ gate: gate({ final_code_recorded: false }) }));
    expect(step(actionSteps(noCode), "code")).toMatchObject({ label: "Record the final code", done: false, enabled: true });
    const recorded = computeReviewNumbers(input({ run: run({ engineer_final_code: "B" }), gate: gate({ final_code_recorded: false }) }));
    expect(recorded.finalCode).toBe("B");
    expect(recorded.finalCodeRecorded).toBe(true);
    expect(step(actionSteps(recorded), "code")).toMatchObject({ label: "Final code: B", done: true, enabled: false });
    expect(computeReviewNumbers(input()).finalCodeRecorded).toBeNull();
  });

  it("a step with 0 is done (shown, not hidden); sign opens only when all are clear and saved", () => {
    const clear = computeReviewNumbers(input({ rows: [row("a1", "A")], gate: gate() }));
    const steps = actionSteps(clear);
    expect(steps).toHaveLength(5);
    expect(steps.slice(0, 4).every((s) => s.done && !s.enabled)).toBe(true);
    expect(step(steps, "sign").enabled).toBe(true);
    expect(step(actionSteps({ ...clear, unsaved: 1 }), "sign").enabled).toBe(false);
    expect(step(actionSteps({ ...clear, unreadPages: [2] }), "sign").enabled).toBe(false);
    expect(step(actionSteps({ ...clear, missingStandards: ["API 610"] }), "sign").enabled).toBe(false);
    expect(step(actionSteps({ ...clear, undecided: 1 }), "sign").enabled).toBe(false);
    expect(step(actionSteps({ ...clear, signLeft: ["record the final code"] }), "sign").enabled).toBe(false);
  });

  /** D4. MUTATION PROOF: drop `&& unsaved === 0` from the decide step's
   *  `done`, or move the save message below the others, and this fails. */
  it("Decide is not done while a decision is unsaved, and Sign says to save first before anything else", () => {
    const clear = computeReviewNumbers(input({ rows: [row("a1", "A")], gate: gate() }));
    const steps = actionSteps({ ...clear, unsaved: 2, unopenedNeedsYou: 1, signLeft: ["record the final code"] });
    expect(step(steps, "decide")).toMatchObject({ done: false, enabled: true, detail: "2 decisions are not saved yet." });
    expect(step(steps, "sign").detail).toBe("Save your 2 decisions first.");
    expect(step(actionSteps({ ...clear, unsaved: 1, standardsKnown: false }), "sign").detail).toBe("Save your 1 decision first.");
  });

  it("sign waits for the issue gate: no final code, unread pages to tick, or the gate unknown", () => {
    const base = { rows: [row("b1", "B")], decisions: { decisions: { b1: { kind: "keep" } }, opened: {} } as DecisionState };
    // Every comment decided and saved, but no final code: off, and says why.
    const noCode = actionSteps(computeReviewNumbers(input({ ...base, gate: gate({ final_code_recorded: false, issuable: false }) })));
    expect(noCode.slice(0, 3).every((s) => s.done)).toBe(true);
    expect(step(noCode, "code").done).toBe(false);
    expect(step(noCode, "sign").enabled).toBe(false);
    expect(step(noCode, "sign").detail).toBe("Before you sign: record the final code.");
    // A page still to tick: the pages step is open and Sign is off.
    const page = actionSteps(computeReviewNumbers(input({
      ...base, gate: gate({ issuable: false, unread_pages: [{ page: 6, reason: null }] } as Partial<CrsIssueGate>),
    })));
    expect(page[1]).toMatchObject({ count: 1, done: false, enabled: true, detail: "Page 6" });
    expect(step(page, "sign").enabled).toBe(false);
    // The gate not read: off.
    expect(step(actionSteps(computeReviewNumbers(input(base))), "sign").enabled).toBe(false);
    // All clear: on.
    expect(step(actionSteps(computeReviewNumbers(input({ ...base, gate: gate() }))), "sign").enabled).toBe(true);
  });

  it("a signed run says Signed and cannot be signed again", () => {
    const signed = computeReviewNumbers(input({ run: run({ crs_issued_at: "2026-10-19T10:00:00" }) }));
    const sign = step(actionSteps(signed), "sign");
    expect(sign.label).toBe("Signed");
    expect(sign.done).toBe(true);
    expect(sign.enabled).toBe(false);
    expect(step(actionSteps(signed), "code")).toMatchObject({ done: true, enabled: false });
  });

  it("pages detail says pages the way a person does", () => {
    expect(pagesDetail([4])).toBe("Page 4");
    expect(pagesDetail([1, 2, 3, 7])).toBe("Pages 1-3 and 7");
    expect(pagesDetail([])).toBe("");
  });
});

describe("verdictLine", () => {
  it("states comments and judgement, then not signed", () => {
    const rows = [...Array.from({ length: 9 }, (_, i) => row(`b${i}`, "B")), row("c1", "C"), row("c2", "C"), row("c3", "C")];
    expect(verdictLine(computeReviewNumbers(input({ rows })), run())).toBe("12 comments, 3 need your judgement. Not signed yet.");
    expect(verdictLine(computeReviewNumbers(input({ rows: [row("b", "B")] })), run())).toBe("1 comment. Not signed yet.");
    expect(verdictLine(computeReviewNumbers(input({ rows: [row("c", "C")] })), run())).toBe("1 comment, 1 needs your judgement. Not signed yet.");
  });

  it("no comments and nothing blocking: ready to sign", () => {
    expect(verdictLine(computeReviewNumbers(input({ rows: [row("a", "A")], gate: gate() })), run())).toBe("No comments. Ready to sign.");
    // No final code yet: not ready.
    const noCode = computeReviewNumbers(input({ rows: [row("a", "A")], gate: gate({ final_code_recorded: false }) }));
    expect(verdictLine(noCode, run())).toBe("No comments. Not signed yet.");
  });

  it("signed: says when", () => {
    const n = computeReviewNumbers(input({ run: run({ crs_issued_at: "2026-10-19T10:00:00" }) }));
    expect(verdictLine(n, run())).toBe("Signed on 19 Oct 2026.");
  });

  it("an unknown number is left out, never shown as 0", () => {
    const n = computeReviewNumbers(input({ rows: [row("b", "B")] }));
    const line = verdictLine({ ...n, comments: Number.NaN }, run());
    expect(line).toBe("Not signed yet.");
    expect(line).not.toMatch(/\b0\b|NaN/);
  });
});
