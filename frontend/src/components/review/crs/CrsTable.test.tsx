/**
 * v2.1 W1: the table's own words are plain: the "Show" choices are
 * explained, and no message says "rows", "depth" or "clauses".
 * MUTATION PROOF: put back "No row to show at this depth." and the first
 * test fails; drop the explanation line and the second fails.
 */
import { render, screen } from "@testing-library/react";
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CrsTable } from "./CrsTable";
import { useCrsDecisions } from "./useCrsDecisions";

function table(over: Partial<Parameters<typeof CrsTable>[0]> = {}) {
  const decisions = renderHook(() => useCrsDecisions()).result.current;
  return (
    <CrsTable
      rows={[]} allRows={[]} counts={{ met: 3, notApplicable: 1, anotherDocument: 0, comment: 0, needsYou: 0 }}
      depth="everything" onDepth={vi.fn()} showMet={false} onShowMet={vi.fn()} spot={new Set()} selectedKey={null}
      onSelect={vi.fn()} onOpenEvidence={vi.fn()} mode={null} onMode={vi.fn()} decisions={decisions}
      clausesNotApplicable={12} {...over}
    />
  );
}

describe("CrsTable words (v2.1 W1)", () => {
  it("an empty list and the not-applicable line use plain words", () => {
    render(table());
    const text = document.body.textContent ?? "";
    expect(text).toContain("Nothing to show with this choice.");
    expect(text).toContain("12 requirements in the standards were judged not to apply to this equipment");
    expect(text).not.toMatch(/\bdepth\b|\bclauses?\b|No row to show|counted on the run/);
  });

  it("explains each Show choice", () => {
    render(table());
    expect(screen.getByTestId("crs-depth-help")).toHaveTextContent(
      "Critical only: only what needs your judgement and clear failures. Standard: every comment for the contractor. Everything: also what met the standard or does not apply.");
  });
});
