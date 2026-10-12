/**
 * Opening another run must not carry the previous run's draft code onto it.
 * Invented identifiers only.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewCodePanel } from "./ReviewCodePanel";
import type { ReviewRunSummary } from "../../types/api";

const decideCode = vi.fn();
vi.mock("../../api/client", () => ({
  reviews: { decideCode: (...args: unknown[]) => decideCode(...args) },
}));

function run(id: string, over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: id, submittal_document_id: "doc_sub",
    submittal_filename: "sheet.pdf", equipment_tags: [], status: "completed",
    created_at: null, completed_at: null, standards_in_scope: 1,
    findings_total: 1, by_status: {}, recommended_code: "Manual Review Required",
    recommended_reason: null, recommended_details: null, completeness: null,
    ...over,
  } as ReviewRunSummary;
}

beforeEach(() => {
  decideCode.mockReset();
  decideCode.mockResolvedValue({ ok: true, data: run("x") });
});

describe("switching runs", () => {
  it("starts run B from B's own values, not A's draft", async () => {
    const { rerender } = render(
      <ReviewCodePanel run={run("run-a", { engineer_final_code: "Approved with Comments", override_reason: "reason for A" })}
        onDecided={vi.fn()} />);
    expect(screen.getByDisplayValue("reason for A")).toBeInTheDocument();

    rerender(<ReviewCodePanel run={run("run-b")} onDecided={vi.fn()} />);
    expect(screen.queryByDisplayValue("reason for A")).toBeNull();
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("Manual Review Required");

    await userEvent.click(screen.getByRole("button", { name: /record|save/i }));
    // Whatever is written, it is addressed to B with B's value.
    expect(decideCode).toHaveBeenCalledWith("run-b", "Manual Review Required", null);
  });
});
