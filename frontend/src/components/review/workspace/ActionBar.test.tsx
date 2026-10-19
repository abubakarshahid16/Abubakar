/**
 * v2.2: "Preview CRS" in the "What you need to do" bar opens the read-only
 * look at the comment sheet under the bar, with "Close preview". It issues
 * nothing. Made-up data only.
 *
 * MUTATION PROOF (done once by hand): drop the `previewOpen` block from
 * ActionBar and "opens the sheet under the bar" fails; drop `readOnly` from
 * CrsLook and "is a look only" fails.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CrsPreview, ReviewReadiness, ReviewRunSummary } from "../../../types/api";
import type { CrsRow, ReviewNumbers, SignOff } from "./contract";
import { ActionBar } from "./ActionBar";
import { actionSteps, computeReviewNumbers } from "./numbers";

const downloadCrs = vi.fn();
const previewCrs = vi.fn();
const issueContractorCopy = vi.fn();
vi.mock("../downloadCrs", () => ({ downloadCrs: (...a: unknown[]) => downloadCrs(...a) }));
vi.mock("../crs/issueContractorCopy", () => ({ issueContractorCopy: (...a: unknown[]) => issueContractorCopy(...a) }));
vi.mock("../../../api/client", () => ({
  api: {},
  reviews: {
    previewCrs: (...a: unknown[]) => previewCrs(...a),
    rereadPages: vi.fn(), setCrsTransmittals: vi.fn(), importCrsReply: vi.fn(), setCrsCommentStatus: vi.fn(),
    recordCrsResponse: vi.fn(), crsCommentHistory: vi.fn(),
  },
}));

function sheet(): CrsPreview {
  return {
    title: "EXAMPLE OPERATING COMPANY", subtitle: "COMMENT RESOLUTION SHEET",
    header: [{ label: "Document Title:", value: "Pump datasheet rev B.pdf" }],
    columns: ["Item No", "Document Name", "Page No./Section", "COMPANY Comments", "Comment By",
      "Contractor's Response", "Final Resolution", "AI Review Comments", "Reasoning (internal)"],
    rows: [{ item_no: 1, row_ref: "RF-1", document_name: "Pump datasheet rev B.pdf", page_section: "p4",
      comment: "Design pressure is below the standard.", comment_by: "Reviewer", contractor_response: "",
      final_resolution: "Open", ai_review_comment: "internal note", reasoning: "internal reasoning", crs_ref: "RF-1" }],
    review_notes: [{ note: "kept inside", standard: "API 610", count: 1, detail: "" }],
    recommended_code: "", recommended_code_label: "Recommended Review Code:", recommended_code_reason: "",
  } as unknown as CrsPreview;
}

const RUN = {
  review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "Pump datasheet rev B.pdf", status: "completed",
} as unknown as ReviewRunSummary;
const READINESS = {
  submittal_document_id: "doc-1", pages_total: 4, pages_read: 4, unread_pages: [], unread_page_reasons: {},
  standards_cited: 1, standards_held: [], standards_missing: [], last_run_id: null, nothing_changed: false, changes: [],
  ledger_state: "current", ledger_note: null,
} as unknown as ReviewReadiness;
const ROW = { key: "b1", tier: { tier: "B", label: "Comment", reason: null }, findings: [{ id: "f" }], priorState: "open" } as unknown as CrsRow;

function numbers(run: ReviewRunSummary = RUN): ReviewNumbers {
  return computeReviewNumbers({
    run, findings: [], rows: [ROW], summary: null, missingStandards: [], readiness: READINESS,
    decisions: { decisions: {}, opened: {} }, unsaved: [], gate: null,
  });
}

const IDLE: SignOff = { busy: false, message: null, error: null, save: vi.fn(), sign: vi.fn(), workingCopy: vi.fn() };

function renderBar(n: ReviewNumbers, onAction = vi.fn(), signOff: SignOff = IDLE) {
  render(<ActionBar run={RUN} numbers={n} steps={actionSteps(n)} onAction={onAction} signOff={signOff} />);
  return onAction;
}

beforeEach(() => {
  downloadCrs.mockReset();
  issueContractorCopy.mockReset();
  previewCrs.mockReset().mockResolvedValue({ ok: true, data: sheet() });
});

describe("Preview CRS (v2.2)", () => {
  it("is step 5 of 6, just before Sign", () => {
    renderBar(numbers());
    const bar = screen.getByTestId("ws-action-bar");
    const items = within(within(bar).getByRole("list", { name: "Steps, in order" })).getAllByRole("listitem");
    expect(items).toHaveLength(6);
    expect(items[4]).toHaveTextContent("5Preview CRS");
    expect(items[5]).toHaveTextContent("6Sign and export");
    expect(within(items[4]).getByRole("button", { name: "Preview CRS" })).toBeEnabled();
  });

  it("opens the sheet under the bar, tells the parent, and closes again", async () => {
    const onAction = renderBar(numbers());
    expect(screen.queryByTestId("ws-crs-preview")).toBeNull();
    const button = screen.getByRole("button", { name: "Preview CRS" });
    await userEvent.click(button);
    expect(onAction).toHaveBeenCalledWith("preview");
    expect(button).toHaveAttribute("aria-expanded", "true");
    const box = screen.getByTestId("ws-crs-preview");
    expect(await within(box).findByText("Design pressure is below the standard.")).toBeInTheDocument();
    expect(previewCrs).toHaveBeenCalledWith("run-1");
    await userEvent.click(within(box).getByRole("button", { name: "Close preview" }));
    expect(screen.queryByTestId("ws-crs-preview")).toBeNull();
  });

  it("is a look only: no internal columns, no buttons but Close, and nothing is issued", async () => {
    renderBar(numbers());
    await userEvent.click(screen.getByRole("button", { name: "Preview CRS" }));
    const box = screen.getByTestId("ws-crs-preview");
    await within(box).findByText("Design pressure is below the standard.");
    expect(box.textContent).not.toContain("internal note");
    expect(box.textContent).not.toContain("Reasoning (internal)");
    expect(within(box).getAllByRole("button").map((b) => b.textContent)).toEqual(["Close preview"]);
    expect(issueContractorCopy).not.toHaveBeenCalled();
    expect(downloadCrs).not.toHaveBeenCalled();
    expect(IDLE.sign).not.toHaveBeenCalled();
  });

  it("stays open for a signed review, so the sheet can still be looked at", async () => {
    const signed = numbers({ ...RUN, crs_issued_at: "2026-10-19T10:00:00" } as unknown as ReviewRunSummary);
    renderBar(signed);
    expect(screen.getByRole("button", { name: "Signed" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Preview CRS" }));
    expect(await within(screen.getByTestId("ws-crs-preview")).findByText("Design pressure is below the standard.")).toBeInTheDocument();
    expect(issueContractorCopy).not.toHaveBeenCalled();
  });

  it("says in plain words when the sheet cannot be loaded", async () => {
    previewCrs.mockResolvedValue({ ok: false, error: { message: "server busy" } });
    renderBar(numbers());
    await userEvent.click(screen.getByRole("button", { name: "Preview CRS" }));
    expect(await screen.findByTestId("ws-crs-preview-error")).toHaveTextContent("The preview of the sheet could not be loaded (server busy).");
  });
});
