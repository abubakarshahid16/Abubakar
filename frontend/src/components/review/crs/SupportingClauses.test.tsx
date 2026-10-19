/**
 * Order 139 part 2 (spec c): a field row shows the clauses behind it under its
 * required action, with the file's cap and count; a row of one clause shows
 * none. Invented data only.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CrsRow } from "./crsRows";
import { SupportingClauses } from "./SupportingClauses";

function row(over: Partial<CrsRow>): CrsRow {
  return { key: "crs:g", crsAction: "Contractor to provide Field x.", clauseCount: 0, clauses: [], ...over } as CrsRow;
}

describe("SupportingClauses", () => {
  it("lists up to ten clauses and says how many more of n", () => {
    const clauses = Array.from({ length: 10 }, (_, i) => `STD-100.pdf, clause 3.${i + 1}`);
    render(<SupportingClauses row={row({ clauseCount: 14, clauses })} />);
    expect(screen.getByText("Supporting clauses (14):")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(11);
    expect(screen.getByText("and 4 more of these 14")).toBeInTheDocument();
  });
  it("shows nothing on a row of one clause or without the file's action line", () => {
    const { container } = render(<>
      <SupportingClauses row={row({ clauseCount: 1, clauses: ["STD-100.pdf, clause 1"] })} />
      <SupportingClauses row={row({ crsAction: null, clauseCount: 3, clauses: ["a", "b", "c"] })} />
    </>);
    expect(container.textContent).toBe("");
  });
});
