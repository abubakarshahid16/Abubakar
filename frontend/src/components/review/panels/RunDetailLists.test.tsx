/**
 * Plan change 6 B: the requirements panel on the Steps page. With the pair,
 * reaching the comparison is not called checked. Made-up counts.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { RequirementSplit, RunCoveragePair } from "../../../types/api";
import { RequirementSplitPanel } from "./RunDetailLists";

const split = {
  checked: 30, applies_not_checked: 10, does_not_apply: 5, total: 45,
  applies_not_checked_reasons: [{ reason: "no field on the sheet", count: 10 }],
  does_not_apply_reasons: [], unchecked_share: 0.25,
} as unknown as RequirementSplit;
const pair = {
  line: "Standard rules decided: 1 of 40 that apply. Risk: not measured.",
  checklist_line: "Checklist apart.", boundary: "Boundary.", decided: 1, applicable: 40, unknown: 39,
} as RunCoveragePair;

describe("RequirementSplitPanel, one meaning of checked", () => {
  afterEach(cleanup);

  it("switch on: decided and reached are apart, and no count says checked", () => {
    render(<RequirementSplitPanel split={split} pair={pair} />);
    expect(screen.getByTestId("split-pair")).toHaveTextContent("1 of 40");
    expect(screen.getByTestId("split-decided")).toHaveTextContent("1 decided by code");
    expect(screen.getByTestId("split-reached")).toHaveTextContent("29 reached the comparison, not decided");
    expect(screen.queryByTestId("split-checked")).toBeNull();
    expect(screen.getByTestId("requirement-split").textContent).not.toMatch(/\bchecked\b/);
    expect(screen.getByTestId("requirement-split")).not.toHaveTextContent("25%");
  });

  it("switch on: decisions above the reached count never print a negative", () => {
    render(<RequirementSplitPanel split={{ ...split, checked: 0 }} pair={pair} />);
    expect(screen.getByTestId("split-reached")).toHaveTextContent("0 reached");
  });

  it("switch off: the three groups and the share stay", () => {
    render(<RequirementSplitPanel split={split} pair={null} />);
    expect(screen.getByTestId("split-checked")).toHaveTextContent("30 checked");
    expect(screen.getByTestId("requirement-split")).toHaveTextContent("25%");
    expect(screen.queryByTestId("split-decided")).toBeNull();
  });
});
