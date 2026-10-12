/**
 * #791: the five step lights, from a synthetic run trace and AI numbers.
 * Each light and each count is pinned so removing one fails a test.
 */
import { describe, expect, it } from "vitest";

import type { AiNumbers, AiStepNumbers, ReviewRunSummary, ReviewTrace, ReviewTraceStep } from "../../types/api";
import { pipelineSteps } from "./pipelineLights";

const tstep = (step: string, counts: Record<string, number>, over: Partial<ReviewTraceStep> = {}): ReviewTraceStep => ({
  step, summary: `${step} summary`, status: "ok", warning: null, counts, items: [], timing: null, ...over,
});

const ai = (step: string, counts: Record<string, number>, over: Partial<AiStepNumbers> = {}): AiStepNumbers => ({
  step, state: "ran", where: "local model", model: "ollama:m", local_instead: null,
  lines: [`${step} line`], counts, ...over,
});

const TRACE: ReviewTrace = {
  review_run_id: "run-1", document: "sheet.pdf", source: "stored", ai: {},
  steps: [
    tstep("READ", { values: 69, pages: 5 }),
    tstep("STANDARDS", { chosen: 4, cited_not_held: 0 }),
    tstep("RULES", { findings: 40, paired: 30 }),
    tstep("DECIDE", { Meets: 20 }),
    tstep("CRS", { rows: 12 }),
  ],
};

const NUMBERS: AiNumbers = {
  reader: ai("AI reader", { pages: 5, pages_read: 5, timed_out: 0, agreed: 10, conflicts: 1, ai_only: 3 }),
  matcher: ai("AI matcher", { asked: 6, proposed: 4, used: 3, held: 1 }),
  engineering_check: ai("AI engineering check", { proposed: 5, kept: 3 }),
  wording: ai("AI wording", { tried: 4, accepted: 3 }),
};

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return { review_run_id: "run-1", findings_total: 40, engineer_final_code: null,
    ai_numbers: NUMBERS, ...over } as unknown as ReviewRunSummary;
}

const byKey = (r: ReviewRunSummary, t: ReviewTrace | null = TRACE) =>
  Object.fromEntries(pipelineSteps(r, t).map((s) => [s.key, s]));

describe("pipeline lights", () => {
  it("is green on every step when each completed and the AI returned something", () => {
    const s = byKey(run());
    expect(Object.values(s).map((x) => x.light)).toEqual(["green", "green", "green", "green", "green"]);
    expect(s.read.reason).toBe("AI read 5 of 5 pages; 3 values added, 10 agreed");
    expect(s.match.reason).toBe("30 of 40 requirements paired; AI proposed 4, 3 used, 1 held");
    expect(s.crs.reason).toBe("12 rows written, 3 AI-worded");
  });

  it("the live F9 case: AI timed out on 4 of 5 pages, 0 values added - amber", () => {
    const r = run({ ai_numbers: { ...NUMBERS, reader: ai("AI reader",
      { pages: 5, pages_read: 1, timed_out: 4, agreed: 0, conflicts: 0, ai_only: 0 }) } });
    const read = byKey(r).read;
    expect(read.light).toBe("amber");
    expect(read.reason).toBe("AI timed out on 4 of 5 pages, 0 values added");
  });

  it("is never green when the AI was asked and returned nothing", () => {
    const r = run({ ai_numbers: { ...NUMBERS,
      matcher: ai("AI matcher", { asked: 6, proposed: 0, used: 0, held: 0 }),
      engineering_check: ai("AI engineering check", { proposed: 0, kept: 0 }),
      wording: ai("AI wording", { tried: 4, accepted: 0 }) } });
    const s = byKey(r);
    expect(s.match.light).toBe("amber");
    expect(s.match.reason).toBe("AI matcher was asked and returned nothing");
    expect(s.decide.light).toBe("amber");
    expect(s.crs.light).toBe("amber");
  });

  it("an AI step that was off, incomplete or not recorded is amber and says which", () => {
    const r = run({ ai_numbers: { ...NUMBERS,
      reader: ai("AI reader", { pages: 5 }, { state: "off" }),
      matcher: ai("AI matcher", {}, { state: "incomplete" }),
      engineering_check: null } });
    const s = byKey(r);
    expect([s.read.light, s.read.reason]).toEqual(["amber", "AI reader off"]);
    expect([s.match.light, s.match.reason]).toEqual(["amber", "AI matcher incomplete"]);
    expect([s.decide.light, s.decide.reason]).toEqual(["amber", "no AI engineering check record for this run"]);
  });

  it("a step that produced nothing is red", () => {
    const empty: ReviewTrace = { ...TRACE, steps: [
      tstep("READ", { values: 0 }), tstep("STANDARDS", { chosen: 0, cited_not_held: 0 }),
      tstep("RULES", { findings: 40, paired: 0 }), tstep("DECIDE", {}),
      tstep("CRS", {}, { status: "failed", warning: "CRS not composed" })] };
    const s = byKey(run({ findings_total: 0 }), empty);
    expect(Object.values(s).map((x) => x.light)).toEqual(["red", "red", "red", "red", "red"]);
    expect(s.match.reason).toBe("none of 40 requirements was paired with a value");
    expect(s.crs.reason).toBe("CRS not composed");
  });

  it("cited standards not in the library make the standards step amber", () => {
    const t = { ...TRACE, steps: TRACE.steps.map((x) => x.step === "STANDARDS"
      ? tstep("STANDARDS", { chosen: 4, cited_not_held: 9 }) : x) };
    expect(byKey(run(), t).standards).toMatchObject({ light: "amber", reason: "9 cited standard(s) not in the library" });
  });

  it("with no stored trace every step names the gap instead of showing zero", () => {
    const s = byKey(run(), null);
    expect(s.read).toMatchObject({ light: "amber", reason: "no read record for this run" });
    expect(s.standards.reason).toBe("no standards record for this run");
    expect(s.crs.reason).toBe("no CRS record for this run");
  });

  it("says what blocks issuing the CRS to the contractor", () => {
    expect(byKey(run()).crs.details).toContain(
      "Export: the issue copy waits for the engineer's final code (the internal copy can be exported).");
    expect(byKey(run({ engineer_final_code: "Code 1" })).crs.details)
      .toContain("Export: ready to issue to the contractor.");
  });

  it("#791: the decide step carries a link per status, each out of all findings", () => {
    const steps = byKey(run({ findings_total: 7, by_status: { COMPLIANT: 4, MISSING_INFORMATION: 3,
      NON_COMPLIANT: 0 } } as Partial<ReviewRunSummary>));
    expect(steps.decide.links).toEqual([
      { status: "COMPLIANT", count: 4, total: 7 },
      { status: "MISSING_INFORMATION", count: 3, total: 7 },
    ]);
  });
});
