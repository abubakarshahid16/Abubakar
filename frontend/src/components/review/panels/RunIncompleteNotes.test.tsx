/**
 * What a run could not check, on the Sheet's header (#967 PR 3). Ported from
 * the old run card's tests (2g, B3, #633); the words are unchanged.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReviewRunSummary } from "../../../types/api";
import { RunIncompleteNotes } from "./RunIncompleteNotes";

const NOMINAL_REASON = "The review used a NOMINAL ESTIMATE denominator because field count is unknown.";

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc-sub", submittal_filename: "drum.pdf",
    equipment_tags: ["V-101"], status: "completed", created_at: "2026-09-20T00:00:00Z",
    completed_at: "2026-09-20T00:01:00Z", standards_in_scope: 2, findings_total: 1,
    by_status: { MISSING_INFORMATION: 1 }, recommended_code: "Manual Review Required",
    recommended_reason: NOMINAL_REASON,
    completeness: { fields_read: 4, fields_estimated: 35, pages: 1, sufficient: false },
    ...over,
  } as ReviewRunSummary;
}

describe("2g: the completeness line speaks plain words, once", () => {
  it("shows the plain reason and no developer word, and does not repeat the fields checked", () => {
    render(<RunIncompleteNotes run={run({
      recommended_reason: "Checked 4 datasheet fields. That is not enough of the datasheet to suggest a review code yet.",
      recommended_details: NOMINAL_REASON,
    })} />);
    expect(screen.queryByText(/Checked 4 datasheet fields/)).toBeNull();
    expect(screen.queryByText(/NOMINAL|denominator|MISSING_LOCALLY/i)).toBeNull();
  });

  it("still states the fields checked when the reason does not", () => {
    render(<RunIncompleteNotes run={run({ recommended_reason: "Not enough was read to recommend a code." })} />);
    expect(screen.getByText("Checked 4 datasheet fields.")).toBeInTheDocument();
    expect(screen.queryByText(/NOMINAL/i)).toBeNull();
  });
});

describe("B3: the pages a run read into fields", () => {
  it("says which pages were not read, with the denominator", () => {
    render(<RunIncompleteNotes run={run({ page_coverage: {
      pages_total: 11, fact_pages: [4, 5], pages_not_read_into_fields: [1, 2, 3, 6, 7, 8, 9, 10, 11],
      not_read_reasons: {},
    } })} />);
    const line = screen.getByTestId("page-coverage");
    expect(line).toHaveTextContent("Fields read from 2 of 11 pages (pages 4-5)");
    expect(line).toHaveTextContent("pages 1-3, 6-11 not read into fields");
  });

  it("shows nothing for a run made before the page ledger existed", () => {
    render(<RunIncompleteNotes run={run()} />);
    expect(screen.queryByTestId("page-coverage")).toBeNull();
  });
});

describe("#633: a run that could not check everything says so", () => {
  it("shows a web check that could not be checked, and findings that are only partial", () => {
    render(<RunIncompleteNotes run={run({
      web_check_status: { ran: false, complete: false, reason: "it failed (RuntimeError)",
                          plain: "Web standards check could not be checked: it failed (RuntimeError)." },
      partial_findings: 3,
    })} />);
    expect(screen.getByTestId("web-check-incomplete")).toHaveTextContent("could not be checked");
    expect(screen.getByTestId("partial-findings")).toHaveTextContent("3 finding(s) were written before this review stopped");
  });

  it("shows neither line for a run with nothing unchecked", () => {
    render(<RunIncompleteNotes run={run({ recommended_reason: "Checked 4 datasheet fields." })} />);
    expect(screen.queryByTestId("web-check-incomplete")).toBeNull();
    expect(screen.queryByTestId("partial-findings")).toBeNull();
    expect(screen.queryByRole("list")).toBeNull();
  });
});
