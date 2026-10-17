/**
 * #603: the findings table shows one page of rows at a time, says which, and
 * starts again at page 1 whenever a filter changes.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ReviewFinding } from "../../types/api";
import { FindingsTable, PAGE_SIZE } from "./FindingsTable";

function finding(n: number, tag: string): ReviewFinding {
  return {
    id: `f-${n}`, document_id: "doc", compliance_status: "NON_COMPLIANT", standard_clause: `${n}.1`,
    requirement: `requirement ${n}`, finding: `finding ${n}`, equipment_tag: tag, contractor_page: 1,
    matched_phrase: `field ${n}`, approval_status: "pending", confirmed_by: null,
  } as unknown as ReviewFinding;
}

const rows = () => within(screen.getByRole("table")).getAllByRole("row").length - 1; // minus the header

describe("#603: findings in pages", () => {
  it("renders one page, names it with its denominator, and walks to the next", async () => {
    const findings = Array.from({ length: PAGE_SIZE + 50 }, (_, i) => finding(i, i < 20 ? "V-1" : "V-2"));
    render(<FindingsTable findings={findings} selectedId={null} onSelect={vi.fn()} />);
    expect(rows()).toBe(PAGE_SIZE);
    expect(screen.getByTestId("findings-page-line")).toHaveTextContent(`Showing rows 1-${PAGE_SIZE} of ${PAGE_SIZE + 50} in the table`);
    expect(screen.getByRole("button", { name: `Previous ${PAGE_SIZE}` })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: `Next ${PAGE_SIZE}` }));
    expect(rows()).toBe(50);
    expect(screen.getByTestId("findings-page-line")).toHaveTextContent(`Showing rows ${PAGE_SIZE + 1}-${PAGE_SIZE + 50} of ${PAGE_SIZE + 50} in the table`);
    expect(screen.getByRole("button", { name: `Next ${PAGE_SIZE}` })).toBeDisabled();
    // a filter change starts again at page 1 of the new list
    await userEvent.selectOptions(screen.getByLabelText("Filter by equipment tag"), "V-2");
    expect(rows()).toBe(PAGE_SIZE);
    expect(screen.getByTestId("findings-page-line")).toHaveTextContent(`Showing rows 1-${PAGE_SIZE} of ${PAGE_SIZE + 30} in the table`);
  });

  it("clamps the page when the list shrinks under it (the list refreshes during a run)", async () => {
    const many = Array.from({ length: PAGE_SIZE + 50 }, (_, i) => finding(i, "V-1"));
    const { rerender } = render(<FindingsTable findings={many} selectedId={null} onSelect={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: `Next ${PAGE_SIZE}` }));
    expect(rows()).toBe(50);
    rerender(<FindingsTable findings={many.slice(0, 90)} selectedId={null} onSelect={vi.fn()} />);
    expect(rows()).toBe(90);
    expect(screen.queryByTestId("findings-page-line")).toBeNull();
    rerender(<FindingsTable findings={many.slice(0, PAGE_SIZE + 10)} selectedId={null} onSelect={vi.fn()} />);
    expect(screen.getByTestId("findings-page-line")).toHaveTextContent(`Showing rows ${PAGE_SIZE + 1}-${PAGE_SIZE + 10} of ${PAGE_SIZE + 10} in the table`);
    expect(rows()).toBe(10);
  });

  it("shows no page controls when everything fits on one page", () => {
    render(<FindingsTable findings={Array.from({ length: 5 }, (_, i) => finding(i, "V-1"))} selectedId={null} onSelect={vi.fn()} />);
    expect(rows()).toBe(5);
    expect(screen.queryByTestId("findings-page-line")).toBeNull();
  });
});
