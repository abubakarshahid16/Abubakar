/**
 * Order 95 piece 5: "How this was reviewed" renders the stored run record
 * and nothing else. Invented identifiers only.
 *
 * MUTATION PROOF: print 0 for a missing field and the minimal-run test
 * fails; compute the unchecked share from `unchecked_share` instead of the
 * two counts and the share test fails (the fixture's stored share is
 * deliberately wrong); drop the Upload link and the missing-standard test
 * fails.
 */
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReviewRunSummary } from "../types/api";
import { NavigationContext } from "../components/NavLink";
import { HowReviewedView } from "./HowReviewedView";

const reviewRuns = vi.fn();
const reviewRunStandards = vi.fn();
vi.mock("../api/client", () => ({
  reviews: {
    reviewRuns: (...a: unknown[]) => reviewRuns(...a),
    // Order 109: the screen asks for its one run; served from the same fixture.
    reviewRun: async (id: string) => {
      const r = await reviewRuns();
      return r?.ok ? { ok: true, data: r.data.runs.find((x: { review_run_id: string }) => x.review_run_id === id) ?? null } : r;
    },
    reviewRunStandards: (...a: unknown[]) => reviewRunStandards(...a),
  },
}));
afterEach(() => { vi.clearAllMocks(); });

/** A run with every field the page reads, in the shape contracts/types.ts gives it. */
function fullRun(): ReviewRunSummary {
  return {
    review_run_id: "run-full", submittal_document_id: "doc-sub", submittal_filename: "PSV-101 datasheet.pdf",
    equipment_tags: ["PSV-101"], status: "completed",
    created_at: "2026-10-17T08:00:00Z", completed_at: "2026-10-17T08:12:34Z",
    standards_in_scope: 2, findings_total: 23,
    by_status: { NON_COMPLIANT: 3, COMPLIANT: 20 },
    review_codes: [], table_values_not_compared: [], partial_findings: 0,
    recommended_code: "Approved with Comments",
    recommended_reason: "3 of 23 checked values do not meet their clause.",
    recommended_details: "Nominal estimate: 94 of approximately 105 fields.",
    standards_change: { previous_run_id: "run-prev", added: ["API 526"], removed: [] },
    engineer_final_code: "Rejected / Revise and Resubmit", override_reason: "Set pressure is wrong.",
    decided_by_name: "An Engineer", decided_at: "2026-10-17T09:00:00Z",
    completeness: { fields_read: 94, fields_estimated: 105, pages: 5 },
    page_coverage: {
      pages_total: 5, fact_pages: [1, 2, 3], pages_not_read_into_fields: [4, 5],
      not_read_reasons: { "4": "no fields found", "5": "scanned page, OCR pending" },
      ocr: { done: 1, pending: 1, not_required: 3 },
      pages_ai_not_read: [4, 5],
      ai_not_read_reasons: { "4": "the ollama reader timed out on this page", "5": "the ollama reader timed out on this page" },
      reading: { status: "incomplete", pages_total: 5, incomplete_pages: [4, 5], reasons: {} },
    },
    requirement_split: {
      checked: 60, applies_not_checked: 20, does_not_apply: 4362, not_used: 7, total: 4449,
      applies_not_checked_reasons: [{ reason: "standard not in library", count: 12 }, { reason: "page not read", count: 8 }],
      does_not_apply_reasons: [{ reason: "other equipment", count: 4000 }, { reason: "definition only", count: 362 }],
      repeats_ignored: 15,
      // Deliberately NOT 20/80: the page must derive the share from the two counts.
      unchecked_share: 0.5,
      reader: { engine: "ollama", model: "qwen2.5vl:7b", pages: 5, pages_read: 3, timed_out: [4, 5],
                code_only: { "4": "timed out", "5": "timed out" }, seconds: 300, agreed: 40, conflicts: 2, ai_only: 6 },
      clause_checks: { sentences: 10, asked: 10, proposed: 4, refused: { "no quote": 1 }, could_not_read: 2 },
    },
    clause_coverage: { applicable: 80, counts: { checked: 60, not_checked: 20 }, checked_share: 0.75, adds_up: true,
                       line: "60 of 80 applicable clauses checked" },
    applicability: { submittal_equipment: ["pressure safety valve"], equipment_source: "classification",
                     checked_general: 30, checked_matching: 50, kept_equipment_unknown: 0, not_applied: 4000 },
    requirements_not_applied: [{ subject: "pumps", submittal_equipment: "pressure safety valve", count: 4000,
      line: "4000 requirements about pumps",
      standards: [{ standard_document_id: "std-1", standard_name: "API 610", count: 4000, clauses: [] }] }],
    ai_check_status: { ran: true, complete: true, calls_made: 2, requested_items: 5, proposed_items: 4, kept_items: 3,
                       rejected: { "no quote": 1 }, reason: null, cost_usd: 0.1, plain: "3 of 4 proposed items kept." },
    ai_numbers: {
      reader: { step: "AI reader", state: "ran", where: "local model", model: "qwen2.5vl:7b", local_instead: null,
                lines: ["3 of 5 page(s) read by the AI; 2 timed out."],
                counts: { pages: 5, pages_read: 3, timed_out: 2, agreed: 40, refused_by_gate: 1 } },
      matcher: { step: "AI matcher", state: "ran", where: "local model", model: "qwen2.5:7b", local_instead: null,
                 lines: ["Asked about 9 of 12 requirement(s)."],
                 counts: { sent: 12, asked: 9, proposed: 7, used: 5, held: 2, refused_by_rule: 1, unavailable: 1 } },
      engineering_check: { step: "AI engineering check", state: "ran", where: null, model: "claude-x", local_instead: null,
                           lines: ["3 of 4 proposed items kept."], counts: { proposed: 4, kept: 3 } },
      wording: { step: "AI wording", state: "off", where: null, model: null, local_instead: null,
                 lines: ["Off: the CRS rows keep their template wording."], counts: {} },
      clause_checks: { step: "AI clause checks", state: "ran", where: "local model", model: "qwen2.5:7b", local_instead: null,
                       lines: ["4 of 10 sentence requirement(s) now have a proposed check."],
                       counts: { sentences: 10, asked: 10, proposed: 4, refused: 1, could_not_read: 2 } },
    },
  } as ReviewRunSummary;
}

function minimalRun(): ReviewRunSummary {
  return {
    review_run_id: "run-min", submittal_document_id: "doc-sub", submittal_filename: null,
    equipment_tags: [], status: "completed", created_at: null, completed_at: null,
    standards_in_scope: 0, findings_total: 0, by_status: {}, recommended_code: null, recommended_reason: null,
    completeness: null, review_codes: [], table_values_not_compared: [], requirements_not_applied: [], partial_findings: 0,
  } as ReviewRunSummary;
}

const standardsRecord = {
  standards: [
    { standard_document_id: "std-1", filename: "API 610.pdf", selection_method: "referenced", selection_reason: "named on page 1",
      confidence: null, included: true, exclusion_reason: null },
    { standard_document_id: "std-2", filename: "API 526.pdf", selection_method: "equipment_type", selection_reason: "PSV",
      confidence: null, included: true, exclusion_reason: null },
  ],
  missing_references: [{ identifier: "ASME VIII", status: "MISSING_LOCALLY" }],
};

function mount(run: ReviewRunSummary, standards: unknown = standardsRecord) {
  reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run] } });
  reviewRunStandards.mockResolvedValue({ ok: true, data: standards });
  const navigate = vi.fn();
  render(
    <NavigationContext.Provider value={navigate}>
      <HowReviewedView runId={run.review_run_id} onBack={vi.fn()} onOpenRun={vi.fn()} onOpenSteps={vi.fn()} />
    </NavigationContext.Provider>,
  );
  return navigate;
}

describe("HowReviewedView on a full run", () => {
  it("renders all seven sections from the stored fields", async () => {
    mount(fullRun());
    expect(await screen.findByTestId("how-pages")).toBeInTheDocument();
    for (const id of ["standards", "clauses", "ai-steps", "time", "versions", "result"]) {
      expect(screen.getByTestId(`how-${id}`)).toBeInTheDocument();
    }
    // the table of contents names all seven
    const nav = screen.getByRole("navigation", { name: "Sections of this page" });
    expect(within(nav).getAllByRole("link")).toHaveLength(7);

    // 1. pages: totals, lists and the source of each
    expect(screen.getByTestId("pages-total")).toHaveTextContent("5");
    expect(screen.getByTestId("pages-total")).toHaveTextContent("from page_coverage.pages_total");
    expect(screen.getByTestId("pages-code")).toHaveTextContent("3");
    expect(screen.getByTestId("pages-code")).toHaveTextContent("pages 1-3");
    expect(screen.getByTestId("pages-ai")).toHaveTextContent("3");
    expect(screen.getByTestId("pages-ai")).toHaveTextContent("of 5");
    expect(screen.getByTestId("pages-timed-out")).toHaveTextContent("2");
    expect(screen.getByTestId("pages-timed-out")).toHaveTextContent("pages 4-5");
    expect(screen.getByTestId("pages-not-read")).toHaveTextContent("pages 4-5");
    expect(screen.getByTestId("pages-not-read-reasons")).toHaveTextContent("Page 5: scanned page, OCR pending");
    expect(screen.getByTestId("pages-no-ocr")).toHaveTextContent("1");
    expect(screen.getByTestId("pages-ai-not-read")).toHaveTextContent("2");
    expect(screen.getByTestId("pages-ai-not-read")).toHaveTextContent("pages 4-5");
    expect(screen.getByTestId("pages-ai-not-read")).toHaveTextContent("from page_coverage.pages_ai_not_read");
    expect(screen.getByTestId("pages-ai-not-read-reasons")).toHaveTextContent("Page 4: the ollama reader timed out on this page");
    expect(screen.getByTestId("pages-reading")).toHaveTextContent("incomplete");
    expect(screen.getByTestId("pages-meaning")).toHaveTextContent(
      /stored the reading as incomplete: 2 of 5 pages were not read in full \(pages 4-5\) - page 4: no fields found; the ollama reader timed out on this page/);
    expect(screen.getByTestId("pages-meaning")).not.toHaveTextContent(/every/i);

    // 2. standards
    expect(screen.getByTestId("standards-in-scope")).toHaveTextContent("2");
    expect(screen.getByTestId("standards-cited")).toHaveTextContent("1");
    expect(screen.getByTestId("standards-held")).toHaveTextContent("API 610.pdf");
    expect(screen.getByTestId("standards-held")).toHaveTextContent("4000 clause(s) not applied");
    expect(screen.getByTestId("standards-held")).toHaveTextContent("API 526.pdf");
    expect(screen.getByTestId("standards-missing")).toHaveTextContent("ASME VIII");

    // 3. clauses: the split and both reason tables
    expect(screen.getByTestId("clauses-checked")).toHaveTextContent("60");
    expect(screen.getByTestId("clauses-not-checked")).toHaveTextContent("20");
    expect(screen.getByTestId("clauses-applied")).toHaveTextContent("80");
    expect(screen.getByTestId("clauses-not-applicable")).toHaveTextContent("4,362");
    expect(screen.getByTestId("clauses-repeats")).toHaveTextContent("15");
    expect(screen.getByTestId("clauses-not-used")).toHaveTextContent("7");
    expect(screen.getByTestId("clauses-not-used")).toHaveTextContent("from requirement_split.not_used");
    expect(screen.getByTestId("clauses-not-checked-reasons")).toHaveTextContent("standard not in library");
    expect(screen.getByTestId("clauses-not-checked-reasons")).toHaveTextContent("12");
    expect(screen.getByTestId("clauses-not-applicable-reasons")).toHaveTextContent("other equipment");
    expect(screen.getByTestId("clauses-applicability")).toHaveTextContent("pressure safety valve");
    expect(screen.getByTestId("clauses-coverage-line")).toHaveTextContent("60 of 80 applicable clauses checked");

    // 4. AI steps: model, counts by key, and the rule-1 default line
    const reader = screen.getByTestId("ai-step-reader");
    expect(reader).toHaveTextContent("qwen2.5vl:7b");
    expect(reader).toHaveTextContent("2 pages (timed_out)");
    expect(reader).toHaveTextContent("40 values (agreed)");
    expect(reader).toHaveTextContent(/On by default \(setting DATASHEET_AI_READER\)/);
    const matcher = screen.getByTestId("ai-step-matcher");
    expect(matcher).toHaveTextContent("9 requirements (asked)");
    expect(matcher).toHaveTextContent("7 requirements (proposed)");
    expect(matcher).toHaveTextContent("5 requirements (used)");
    expect(matcher).toHaveTextContent("1 requirements (refused_by_rule)");
    const check = screen.getByTestId("ai-step-engineering_check");
    expect(check).toHaveTextContent("5 items (requested_items)");
    expect(check).toHaveTextContent("3 items (kept_items)");
    expect(check).toHaveTextContent("1 items (rejected)");
    expect(screen.getByTestId("ai-step-applicability")).toHaveTextContent(/Off by default \(setting AI_APPLICABILITY_ENABLED\)/);
    expect(screen.getByTestId("ai-step-wording")).toHaveTextContent("off");

    // 5. time
    expect(screen.getByTestId("time-duration")).toHaveTextContent("12 min 34 s");
    expect(screen.getByTestId("time-reader")).toHaveTextContent("5 min");

    // 6. versions
    expect(screen.getByTestId("versions-previous")).toHaveTextContent("run-prev");
    expect(screen.getByTestId("versions-added")).toHaveTextContent("API 526");
    expect(screen.getByTestId("versions-removed")).toHaveTextContent("none");
    // Order 124 item 9: a scope difference against the previous COMPLETED
    // run, never "removed" (which read as deleted from the library).
    expect(screen.getByText("Previous completed run")).toBeInTheDocument();
    expect(screen.getByText("Standards not used in this review (used last time)")).toBeInTheDocument();
    expect(screen.queryByText(/removed since the previous run/)).toBeNull();
    // absent from the runs list = not sent; null would be "not recorded"
    expect(screen.getByTestId("versions-code")).toHaveTextContent("not sent to this page");
    expect(screen.getByTestId("versions-settings")).toHaveTextContent("not sent to this page");

    // 7. result
    expect(screen.getByTestId("result-code")).toHaveTextContent("Approved with Comments");
    expect(screen.getByTestId("result-reason")).toHaveTextContent("3 of 23 checked values");
    expect(screen.getByTestId("result-details")).toHaveTextContent("Nominal estimate");
    expect(screen.getByTestId("result-final")).toHaveTextContent("Rejected / Revise and Resubmit (An Engineer");
    expect(screen.getByTestId("result-final")).toHaveTextContent("Set pressure is wrong.");
  });

  it("derives the unchecked share from applies_not_checked / (checked + applies_not_checked)", async () => {
    const run = fullRun();
    mount(run);
    const split = run.requirement_split!;
    const expected = Math.round((split.applies_not_checked / (split.checked + split.applies_not_checked)) * 1000) / 10;
    const line = await screen.findByTestId("clauses-unchecked-share");
    expect(expected).toBe(25);
    expect(line).toHaveTextContent(`${expected}% - 20 not checked of the 80 that apply`);
    // the engine's own (here deliberately different) stored share is shown as what it is, beside it
    expect(line).toHaveTextContent("50% (requirement_split.unchecked_share)");
  });

  it("#620: says which Company standards the run left out while they wait for an administrator", async () => {
    const sentence = "1 Company standard was not used in this review: uploaded by a non-administrator, "
      + "waiting for an administrator's confirmation. Company standards uploaded before 2026-10-18 count as confirmed.";
    mount(fullRun(), { ...standardsRecord, held_for_confirmation: {
      count: 1, standard_document_ids: ["std-held"], confirm_from: "2026-10-18T00:00:00", sentence } });
    expect(await screen.findByTestId("standards-held-for-confirmation")).toHaveTextContent(sentence);
  });

  it("links each missing standard to the Documents screen for upload", async () => {
    const navigate = mount(fullRun());
    const missing = await screen.findByTestId("standards-missing");
    const link = within(missing).getByRole("link", { name: /Upload it on the Documents screen/ });
    expect(link).toHaveAttribute("href", "/documents");
    link.click();
    expect(navigate).toHaveBeenCalledWith("documents", undefined);
  });
});

describe("HowReviewedView with an unsure equipment type (order 142)", () => {
  it("shows why the type is unsure instead of saying the equipment is not named", async () => {
    const run = fullRun();
    const reason = "equipment type unsure: read as heat exchanger (from its classification), but the datasheet "
      + "states ASME VIII as its Design code (page 1), a code for a pressure vessel. An engineer should confirm the equipment type.";
    run.applicability = { submittal_equipment: [], equipment_source: "unsure", checked_general: 3, checked_matching: 0,
                          kept_equipment_unknown: 5, not_applied: 0, equipment_unsure: reason };
    mount(run);
    const line = await screen.findByTestId("clauses-applicability");
    expect(line).toHaveTextContent(reason);
    expect(line).toHaveTextContent("5 kept because the equipment type is unsure");
    expect(line).not.toHaveTextContent("not named");
  });
});

describe("HowReviewedView on a minimal run", () => {
  it('shows "not recorded on this review" instead of 0 or blank for every missing field', async () => {
    mount(minimalRun(), { standards: [], missing_references: [] });
    await screen.findByTestId("how-pages");
    for (const id of ["pages-total", "pages-code", "pages-ai", "pages-ai-not-read", "pages-timed-out", "pages-not-read",
                      "pages-no-ocr", "pages-reading",
                      "clauses-total", "clauses-checked", "clauses-not-checked", "clauses-applied", "clauses-repeats",
                      "clauses-not-used", "time-created", "time-completed", "time-duration", "time-reader",
                      "versions-previous", "versions-added",
                      "result-code", "result-reason", "result-details", "result-final"]) {
      const el = screen.getByTestId(id);
      expect(el, id).toHaveTextContent("not recorded on this review");
      expect(within(el).queryByText(/^0$/), id).toBeNull();
    }
    expect(screen.getByTestId("clauses-unchecked-share")).toHaveTextContent("not recorded on this review");
    expect(screen.getByTestId("clauses-applicability")).toHaveTextContent("not recorded on this review");
    for (const key of ["reader", "matcher", "clause_checks", "engineering_check", "wording"]) {
      expect(screen.getByTestId(`ai-step-${key}`)).toHaveTextContent("not recorded on this review");
    }
    expect(screen.getByTestId("pages-meaning")).toHaveTextContent(/No page of this document was accounted for/);
  });

  it("says the standards record could not be loaded rather than listing none", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [minimalRun()] } });
    reviewRunStandards.mockResolvedValue({ ok: false, error: { message: "HTTP 500" } });
    render(<HowReviewedView runId="run-min" onBack={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/standards record for this run could not be loaded/);
    expect(screen.queryByText(/No standard was selected/)).toBeNull();
    expect(screen.getByTestId("standards-cited")).toHaveTextContent("not recorded on this review");
  });

  it("says when the run is not in the list", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [] } });
    reviewRunStandards.mockResolvedValue({ ok: true, data: { standards: [] } });
    render(<HowReviewedView runId="run-none" onBack={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("This review could not be found.");
  });
});
