/** P2: the engineer's add/remove-standard control. Mutations M876-M879. */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewRunStandard } from "../../types/api";
import { StandardOverrideControl } from "./StandardOverrideControl";

const all = vi.fn();
const override = vi.fn();
vi.mock("../../api/client", () => ({
  reviews: {
    reviewRunStandardsAll: (...a: unknown[]) => all(...a),
    overrideRunStandard: (...a: unknown[]) => override(...a),
  },
}));

function std(id: string, included: boolean): ReviewRunStandard {
  return { standard_document_id: id, filename: `${id}.pdf`, selection_method: included ? "referenced" : "semantic",
    selection_reason: "r", confidence: null, included, exclusion_reason: included ? null : "not selected" };
}

beforeEach(() => {
  all.mockReset(); override.mockReset();
  all.mockResolvedValue({ ok: true, data: { standards: [std("APPLIED", true), std("OTHER", false)] } });
});

describe("the engineer changes a review's standards", () => {
  it("adds a standard only with a reason, and reports the recomputed list", async () => {
    override.mockResolvedValue({ ok: true, data: { standards: [std("APPLIED", true), std("OTHER", true)], missing_references: [] } });
    const changed = vi.fn();
    render(<StandardOverrideControl runId="run1" decided={false} onChanged={changed} />);
    await userEvent.selectOptions(await screen.findByRole("combobox"), "OTHER");
    const go = screen.getByRole("button", { name: /Add and recompute/ });
    expect(go).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox"), "the sheet's service needs it");
    await userEvent.click(go);
    expect(override).toHaveBeenCalledWith("run1", { standard_document_id: "OTHER", include: true,
      reason: "the sheet's service needs it" });
    expect(changed).toHaveBeenCalled();
    expect(changed.mock.calls[0][0].map((s: ReviewRunStandard) => s.standard_document_id)).toEqual(["APPLIED", "OTHER"]);
  });

  it("removes a standard with the engineer's reason", async () => {
    override.mockResolvedValue({ ok: true, data: { standards: [std("APPLIED", false)], missing_references: [] } });
    render(<StandardOverrideControl runId="run1" decided={false} onChanged={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Remove APPLIED.pdf" }));
    await userEvent.type(screen.getByRole("textbox"), "fixed equipment only");
    await userEvent.click(screen.getByRole("button", { name: /Remove and recompute/ }));
    expect(override).toHaveBeenCalledWith("run1", { standard_document_id: "APPLIED", include: false,
      reason: "fixed equipment only" });
  });

  it("shows the server's refusal instead of pretending it worked", async () => {
    override.mockResolvedValue({ ok: false, error: { message: "you cannot read every standard this review uses" } });
    const changed = vi.fn();
    render(<StandardOverrideControl runId="run1" decided={false} onChanged={changed} />);
    await userEvent.click(await screen.findByRole("button", { name: "Remove APPLIED.pdf" }));
    await userEvent.type(screen.getByRole("textbox"), "no");
    await userEvent.type(screen.getByRole("textbox"), "t this");
    await userEvent.click(screen.getByRole("button", { name: /Remove and recompute/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot read every standard/);
    expect(changed).not.toHaveBeenCalled();
  });

  it("offers no change once an engineer has decided the code", () => {
    render(<StandardOverrideControl runId="run1" decided onChanged={vi.fn()} />);
    expect(screen.getByTestId("override-locked")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
