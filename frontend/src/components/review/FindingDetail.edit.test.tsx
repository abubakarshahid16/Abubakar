/**
 * Owner order section 3: Edit and Reject comment on a finding.
 *
 * Edit saves the engineer's own wording (which the server confirms under
 * their name and prints on the sheet in place of the machine's text); Reject
 * leaves the comment off the sheet without deleting the finding.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewFinding } from "../../types/api";
import { FindingDetail } from "./FindingDetail";

const documentCall = vi.fn();
const update = vi.fn();

vi.mock("../../api/client", () => ({
  api: { document: (...args: unknown[]) => documentCall(...args) },
  reviews: {
    update: (...args: unknown[]) => update(...args),
    confirm: vi.fn(),
    rejectPairing: vi.fn(),
  },
}));

function finding(over: Partial<ReviewFinding> = {}): ReviewFinding {
  return {
    id: "f-1",
    document_id: "doc-sub",
    standard_document_id: null,
    finding: "the noise level exceeds 90 dB(A)",
    requirement: "noise level",
    requirement_source_text: "The noise level shall not exceed 90 dB(A).",
    contractor_evidence_text: null,
    contractor_page: 1,
    standard_page: null,
    standard_clause: null,
    compliance_status: "NON_COMPLIANT",
    confirmed_by: null,
    confirmed_at: null,
    engineer_comment: null,
    approval_status: null,
    requirement_id: "req-1",
    fact_id: "fact-1",
    ...over,
  } as unknown as ReviewFinding;
}

beforeEach(() => {
  documentCall.mockReset();
  update.mockReset();
  documentCall.mockResolvedValue({ ok: false, error: { message: "not found" } });
  update.mockResolvedValue({ ok: true, data: finding() });
});

describe("Edit comment", () => {
  it("saves the engineer's wording and reports the change", async () => {
    const onChanged = vi.fn();
    render(<FindingDetail finding={finding()} documents={[]} onChanged={onChanged} />);

    await userEvent.click(screen.getByRole("button", { name: "Edit comment" }));
    const box = screen.getByLabelText(/comment as it will read on the sheet/i);
    await userEvent.clear(box);
    await userEvent.type(box, "Contractor to state the noise level at 1 m.");
    await userEvent.click(screen.getByRole("button", { name: "Save comment" }));

    expect(update).toHaveBeenCalledWith("f-1", {
      engineer_comment: "Contractor to state the noise level at 1 m.",
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it("prefills the textarea with the existing engineer_comment", async () => {
    render(<FindingDetail finding={finding({ engineer_comment: "Already edited." })} documents={[]} onChanged={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Edit comment" }));
    expect(screen.getByLabelText(/comment as it will read on the sheet/i)).toHaveValue("Already edited.");
  });

  it("refuses an empty comment without calling the API", async () => {
    render(<FindingDetail finding={finding()} documents={[]} onChanged={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Edit comment" }));
    const box = screen.getByLabelText(/comment as it will read on the sheet/i);
    await userEvent.clear(box);
    await userEvent.click(screen.getByRole("button", { name: "Save comment" }));

    expect(update).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("The comment cannot be empty.");
  });

  it("shows the engineer's own wording once saved", () => {
    render(<FindingDetail finding={finding({ engineer_comment: "My own words." })} documents={[]} onChanged={vi.fn()} />);
    expect(screen.getByTestId("engineer-comment")).toHaveTextContent("My own words.");
  });
});

describe("Reject comment", () => {
  it("marks the finding rejected without deleting it", async () => {
    const onChanged = vi.fn();
    render(<FindingDetail finding={finding()} documents={[]} onChanged={onChanged} />);
    await userEvent.click(screen.getByRole("button", { name: "Reject comment" }));

    expect(update).toHaveBeenCalledWith("f-1", { approval_status: "rejected" });
    expect(onChanged).toHaveBeenCalled();
  });

  it("shows the rejected note and disables the button when already rejected", () => {
    render(<FindingDetail finding={finding({ approval_status: "rejected" })} documents={[]} onChanged={vi.fn()} />);
    expect(screen.getByTestId("comment-rejected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Comment rejected" })).toBeDisabled();
  });
});
