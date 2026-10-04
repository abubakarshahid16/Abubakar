/**
 * Selecting another finding must drop the previous finding's edit draft.
 * Invented identifiers only.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewFinding } from "../../types/api";
import { FindingDetail } from "./FindingDetail";

const update = vi.fn();
vi.mock("../../api/client", () => ({
  api: { document: vi.fn(async () => ({ ok: false, error: { message: "nf" } })) },
  reviews: { update: (...a: unknown[]) => update(...a), confirm: vi.fn(), rejectPairing: vi.fn() },
}));

const finding = (id: string): ReviewFinding => ({
  id, document_id: "doc-sub", standard_document_id: null,
  finding: `finding ${id}`, requirement: "noise level",
  requirement_source_text: "text", contractor_evidence_text: null,
  contractor_page: 1, standard_page: null, standard_clause: null,
  compliance_status: "NON_COMPLIANT", confirmed_by: null, confirmed_at: null,
  engineer_comment: null, approval_status: null, requirement_id: "req", fact_id: "fact",
}) as unknown as ReviewFinding;

beforeEach(() => {
  update.mockReset();
  update.mockResolvedValue({ ok: true, data: finding("x") });
});

describe("switching findings", () => {
  it("does not carry an open edit draft from finding A onto finding B", async () => {
    const { rerender } = render(
      <FindingDetail finding={finding("f-a")} documents={[]} onChanged={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Edit comment" }));
    await userEvent.type(screen.getByLabelText(/comment as it will read on the sheet/i), "edited text for A");

    rerender(<FindingDetail finding={finding("f-b")} documents={[]} onChanged={vi.fn()} />);
    // Edit mode is closed again and nothing is saved onto B.
    expect(screen.queryByLabelText(/comment as it will read on the sheet/i)).toBeNull();
    expect(screen.queryByDisplayValue("edited text for A")).toBeNull();
    expect(update).not.toHaveBeenCalled();
  });
});
