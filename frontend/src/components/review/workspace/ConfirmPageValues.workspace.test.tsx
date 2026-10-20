/**
 * Order 164.1, placement: the "Confirm page values" button is where the owner
 * works, in the evidence panel of the REAL workspace sheet (not the old cards
 * view, which nothing in the app imports any more).
 *
 * MUTATION PROOF: take the button out of CrsEvidenceDrawer and "is in the
 * evidence panel" fails; stop passing onValuesConfirmed down and "reads the
 * run again" fails; pass the row's page instead of the shown page and "follows
 * the page shown" fails.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewFinding, ReviewRunSummary } from "../../../types/api";
import { buildCrsRows } from "../crs/crsRows";
import { EMPTY_FACTS } from "../crs/tiers";
import { useCrsDecisions } from "../crs/useCrsDecisions";
import { computeReviewNumbers } from "./numbers";
import { WorkspaceSheet } from "./WorkspaceSheet";

const crsDecisions = vi.fn();
const pageFacts = vi.fn();
const confirmPageFacts = vi.fn();
vi.mock("../../../api/client", () => ({
  reviews: {
    crsDecisions: (...a: unknown[]) => crsDecisions(...a),
    pageFacts: (...a: unknown[]) => pageFacts(...a),
    confirmPageFacts: (...a: unknown[]) => confirmPageFacts(...a),
  },
}));
vi.mock("../sheet/SheetPageImage", () => ({
  SheetPageImage: ({ page }: { page: number }) => <span>{`datasheet page ${page}`}</span>,
}));

const RUN = {
  review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "Pump datasheet rev B.pdf",
  status: "completed", requirement_split: null,
} as unknown as ReviewRunSummary;

const FINDINGS = [
  {
    id: "flange", compliance_status: "NON_COMPLIANT", matched_phrase: "Flange rating", finding: "flange found",
    required_action: "Contractor to fix flange.", contractor_page: 2, approval_status: "pending",
    standard_document_id: "std-1", standard_clause: "6.1", created_at: "2026-10-15T08:00:00Z",
  },
] as unknown as ReviewFinding[];
const ROWS = buildCrsRows(FINDINGS, EMPTY_FACTS, new Map([["std-1", "API 610"]]));

function Live({ onValuesConfirmed }: { onValuesConfirmed: () => void }) {
  const decisions = useCrsDecisions();
  const [open, setOpen] = useState<string | null>(null);
  const numbers = computeReviewNumbers({
    run: RUN, findings: FINDINGS, rows: ROWS, summary: null, missingStandards: [], readiness: null,
    decisions: decisions.state, unsaved: decisions.unsaved, gate: null,
  });
  return (
    <WorkspaceSheet
      runId="run-1" run={RUN} rows={ROWS} submittal={null} standardNames={new Map([["std-1", "API 610"]])}
      decisions={decisions} openRowKey={open} numbers={numbers} onOpenRow={setOpen}
      onValuesConfirmed={onValuesConfirmed}
    />
  );
}

beforeEach(() => {
  crsDecisions.mockReset().mockResolvedValue({ ok: true, data: { decisions: [] } });
  pageFacts.mockReset().mockResolvedValue({
    ok: true,
    data: {
      review_run_id: "run-1", page: 2, boundary: "the values read on this page",
      facts: [{ fact_id: "f1", field: "Flange rating", value: "150", unit: "lb", quote: "Flange rating 150 lb",
        confirmed: false, conflict: false, needs_check: true }],
    },
  });
  confirmPageFacts.mockReset().mockResolvedValue({
    ok: true,
    data: { review_run_id: "run-1", confirmed: 1, already_confirmed: 0, held_before: 1, held_after: 0,
      status_before: {}, status_after: {}, boundary: "this review run" },
  });
});

describe("Confirm page values in the workspace", () => {
  it("is in the evidence panel, follows the page shown, and reads the run again after a confirmation", async () => {
    const user = userEvent.setup();
    const onValuesConfirmed = vi.fn();
    render(<Live onValuesConfirmed={onValuesConfirmed} />);

    await user.click(screen.getByRole("button", { name: /Open evidence for Comment 1/ }));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText("datasheet page 2")).toBeInTheDocument();

    await user.click(within(drawer).getByRole("button", { name: "Confirm page values" }));
    await waitFor(() => expect(pageFacts).toHaveBeenCalledWith("run-1", 2));
    await user.click(await within(drawer).findByRole("checkbox"));
    await user.click(within(drawer).getByRole("button", { name: "Confirm 1 value" }));

    await waitFor(() => expect(confirmPageFacts).toHaveBeenCalledWith("run-1", ["f1"]));
    expect(confirmPageFacts).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(onValuesConfirmed).toHaveBeenCalledTimes(1));
    expect(await within(drawer).findByText(/1 confirmed; in this review 1 finding now has a verdict/)).toBeInTheDocument();
  });
});
