/** Order 14, review round 3: ONE reason rule for every final-code picker. An approving code on a one-run screen (whose proposal is
 *  withheld) must offer the reason field, so the server's 422 is never a dead end. Invented values only. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewRunSummary } from "../../types/api";
import { MAYBE_OPEN_REASON_LABEL, OPEN_REASON_LABEL, reasonRule } from "./codeReason";
import { FinalCode } from "./crs/BeforeYouSign";
import { ReviewCodePanel } from "./ReviewCodePanel";
import { DecisionCard } from "./sheet/DecisionCard";

const decideCode = vi.fn();
vi.mock("../../api/client", () => ({ reviews: { decideCode: (...a: unknown[]) => decideCode(...a) } }));

const NOTE = "No review code proposed: see the review page.";
const run = (over: Partial<ReviewRunSummary> = {}): ReviewRunSummary => ({
  review_run_id: "run-7", submittal_document_id: "doc-7", submittal_filename: "invented.pdf", equipment_tags: [], status: "completed",
  created_at: null, completed_at: null, standards_in_scope: 1, findings_total: 3, by_status: {},
  recommended_code: null, recommended_code_note: NOTE, engineer_final_code: null, override_reason: null, ...over,
} as ReviewRunSummary);

const radio = (value: string) => screen.getAllByRole("radio").find((r) => (r as HTMLInputElement).value === value) as HTMLElement;

beforeEach(() => { decideCode.mockReset(); decideCode.mockResolvedValue({ ok: true, data: run() }); });

describe("the rule", () => {
  it("differs: required; approving with points open: required; approving, unknown: shown; otherwise none", () => {
    expect(reasonRule("Rejected / Revise and Resubmit", "Approved", 0)).toEqual({ show: true, required: true, because: "differs" });
    expect(reasonRule("Approved", null, 3)).toEqual({ show: true, required: true, because: "open" });
    expect(reasonRule("Approved with Comments", null, null)).toEqual({ show: true, required: false, because: "maybe_open" });
    expect(reasonRule("Approved", null, 0).show).toBe(false);
    expect(reasonRule("Rejected / Revise and Resubmit", null, 3).show).toBe(false);
    expect(reasonRule("", null, 3).show).toBe(false);
  });
  it("labels", () => { expect(MAYBE_OPEN_REASON_LABEL.startsWith(OPEN_REASON_LABEL)).toBe(true); });
});

describe("each older picker offers the reason for an approving code when the run's own proposal is withheld", () => {
  it("ReviewCodePanel", async () => {
    render(<ReviewCodePanel run={run()} onDecided={vi.fn()} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "Approved" } });
    fireEvent.change(screen.getByLabelText(MAYBE_OPEN_REASON_LABEL), { target: { value: "invented reason" } });
    fireEvent.click(screen.getByRole("button", { name: "Record final code" }));
    await waitFor(() => expect(decideCode).toHaveBeenCalledWith("run-7", "Approved", "invented reason"));
  });
  it("FinalCode (before you sign)", async () => {
    render(<FinalCode run={run()} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByRole("radio", { name: "Approved with Comments" }));
    fireEvent.change(screen.getByLabelText(MAYBE_OPEN_REASON_LABEL), { target: { value: "invented reason" } });
    fireEvent.click(screen.getByRole("button", { name: "Record the final code" }));
    await waitFor(() => expect(decideCode).toHaveBeenCalledWith("run-7", "Approved with Comments", "invented reason"));
  });
  it("DecisionCard", async () => {
    render(<DecisionCard run={run()} onDecided={vi.fn()} />);
    fireEvent.click(radio("Approved"));
    fireEvent.change(screen.getByLabelText(MAYBE_OPEN_REASON_LABEL), { target: { value: "invented reason" } });
    fireEvent.click(screen.getByRole("button", { name: "Record my decision" }));
    await waitFor(() => expect(decideCode).toHaveBeenCalledWith("run-7", "Approved", "invented reason"));
  });
  it("a code that lets nothing proceed shows no reason field", () => {
    render(<DecisionCard run={run()} onDecided={vi.fn()} />);
    fireEvent.click(radio("Rejected / Revise and Resubmit"));
    expect(screen.queryByLabelText(MAYBE_OPEN_REASON_LABEL)).toBeNull();
  });
});
