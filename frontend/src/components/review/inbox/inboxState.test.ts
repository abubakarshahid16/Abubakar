/**
 * Order 95 piece 3: the inbox state of a document, from its newest run.
 *
 * MUTATION PROOF: move the `crs_issued_at` check below the status checks and
 * "a signed run that later failed a re-check" fails; drop the `other` branch
 * (return ready for any status) and "a status it does not know is never
 * Ready" fails; turn the missing step into 0 and "running with no step
 * recorded" fails.
 */
import { describe, expect, it } from "vitest";

import type { ReviewRunSummary } from "../../../types/api";
import { anyMoving, inFilter, inboxStateOf, stateLabel } from "./inboxState";

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "a.pdf",
    equipment_tags: [], status: "completed", created_at: "2026-10-01T00:00:00Z",
    standards_in_scope: 1, findings_total: 0, by_status: {},
    ...over,
  } as ReviewRunSummary;
}

const job = (over: Record<string, unknown>) => ({
  id: "job-1", state: "running", progress_done: 1, progress_total: 3,
  progress_label: "selecting the applicable standards", cancel_requested: false, ...over,
});

describe("inboxStateOf", () => {
  it("a document with no run is Not reviewed", () => {
    expect(stateLabel(inboxStateOf(undefined))).toBe("Not reviewed");
  });

  it("a completed run is Ready, and its counts show only when they are known", () => {
    const state = inboxStateOf(run());
    expect(stateLabel(state)).toBe("Ready");
    expect(stateLabel(state, { findings: 3, needs_you: 1 })).toBe("Ready: 3 findings to decide, 1 needs you");
    expect(stateLabel(state, { findings: 1, needs_you: 1 })).toBe("Ready: 1 finding to decide, 1 needs you");
    // A-1126: findings, never "comments" - and large counts with separators.
    expect(stateLabel(state, { findings: 6584, needs_you: 6557 })).toBe("Ready: 6,584 findings to decide, 6,557 need you");
  });

  it("a run whose contractor copy was issued is Signed, before any other status", () => {
    expect(inboxStateOf(run({ crs_issued_at: "2026-10-02T00:00:00Z" })).kind).toBe("signed");
    // a signed run that later failed a re-check is still the signed one
    expect(inboxStateOf(run({ status: "failed", crs_issued_at: "2026-10-02T00:00:00Z" })).kind).toBe("signed");
  });

  it("a failed run says why, and says so when no reason was stored", () => {
    expect(stateLabel(inboxStateOf(run({ status: "failed", failure_reason: "the worker stopped" }))))
      .toBe("Failed: the worker stopped");
    expect(stateLabel(inboxStateOf(run({ status: "failed", failure_reason: null }))))
      .toBe("Failed: no reason was recorded");
  });

  it("a queued run or job is Queued", () => {
    expect(stateLabel(inboxStateOf(run({ status: "queued" })))).toBe("Queued");
    expect(stateLabel(inboxStateOf(run({ status: "pending", job: job({ state: "retrying" }) })))).toBe("Queued");
  });

  it("a running job shows its step, one-based, with its name", () => {
    expect(stateLabel(inboxStateOf(run({ status: "running", job: job({}) }))))
      .toBe("Running · step 2 of 3: selecting the applicable standards");
  });

  it("running with no step recorded says Running and nothing more - never step 0", () => {
    const label = stateLabel(inboxStateOf(run({
      status: "running", job: job({ progress_done: null, progress_total: null, progress_label: null }),
    })));
    expect(label).toBe("Running");
  });

  it("a status it does not know is never Ready: it is shown as itself", () => {
    const state = inboxStateOf(run({ status: "half_done" }));
    expect(state.kind).toBe("other");
    expect(stateLabel(state)).toBe("half_done");
    // shown as itself AND under the default chip: an unknown state never vanishes
    expect(inFilter(state, "needs_me")).toBe(true);
  });

  it("a completed run is Ready even while its job row still says running or queued", () => {
    expect(inboxStateOf(run({ status: "completed", job: job({}) })).kind).toBe("ready");
    expect(inboxStateOf(run({ status: "completed", job: job({ state: "queued" }) })).kind).toBe("ready");
  });

  it("a job finishing its last step never reads step 4 of 3", () => {
    const label = stateLabel(inboxStateOf(run({
      status: "running", job: job({ progress_done: 3, progress_total: 3, progress_label: "comparing" }),
    })));
    expect(label).toBe("Running: comparing");
  });
});

describe("inFilter and anyMoving", () => {
  it("Needs me is everything but Signed, Queued and Running - a cancelled or unknown state never vanishes", () => {
    const kinds = {
      ready: inboxStateOf(run()),
      failed: inboxStateOf(run({ status: "failed" })),
      notReviewed: inboxStateOf(undefined),
      signed: inboxStateOf(run({ crs_issued_at: "2026-10-02T00:00:00Z" })),
      queued: inboxStateOf(run({ status: "queued" })),
      running: inboxStateOf(run({ status: "running", job: job({}) })),
      cancelled: inboxStateOf(run({ status: "cancelled" })),
      other: inboxStateOf(run({ status: "half_done" })),
    };
    expect(Object.entries(kinds).filter(([, s]) => inFilter(s, "needs_me")).map(([k]) => k))
      .toEqual(["ready", "failed", "notReviewed", "cancelled", "other"]);
    expect(Object.entries(kinds).filter(([, s]) => inFilter(s, "in_progress")).map(([k]) => k))
      .toEqual(["queued", "running"]);
    expect(anyMoving([kinds.ready, kinds.signed])).toBe(false);
    expect(anyMoving([kinds.ready, kinds.running])).toBe(true);
  });
});
