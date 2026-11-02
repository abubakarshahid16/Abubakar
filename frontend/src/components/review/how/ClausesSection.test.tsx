/**
 * Plan change 6 B: with the switch on the run carries `coverage_pair`, and
 * "checked" has one meaning on this section: reaching the comparison is not a
 * decision. With no pair the old words stay. Made-up run.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ReviewRunSummary } from "../../../types/api";
import { ClausesSection } from "./ClausesSection";

const split = {
  checked: 30, applies_not_checked: 10, does_not_apply: 5, not_used: 2, total: 47, repeats_ignored: 1,
  applies_not_checked_reasons: [], does_not_apply_reasons: [], unchecked_share: 0.25,
};
const pair = {
  line: "Standard rules decided: 1 of 40 that apply (pass 1, fail 0, unknown 39). Risk: not measured.",
  checklist_line: "Checklist, stated apart, not added to the rules: 2 of 3 items decided.",
  boundary: "Boundary: the standard rules this run states apply.",
  decided: 1, applicable: 40, unknown: 39,
};
const clause = { applicable: 44, counts: {}, checked_share: 2.3, adds_up: true, line: "1 of 44 applicable requirement(s) checked" };

function show(over: object) {
  render(<ClausesSection run={{ review_run_id: "r", requirement_split: split, clause_coverage: clause, ...over } as unknown as ReviewRunSummary} />);
}

describe("ClausesSection, one meaning of checked", () => {
  afterEach(cleanup);

  it("switch on: decided comes from the pair and no count is called checked", () => {
    show({ coverage_pair: pair });
    expect(screen.getByTestId("clauses-decided")).toHaveTextContent("Decided by code (pass or fail)");
    expect(screen.getByTestId("clauses-decided")).toHaveTextContent("1");
    expect(screen.getByTestId("clauses-reached")).toHaveTextContent("30");
    expect(screen.queryByTestId("clauses-checked")).toBeNull();
    expect(screen.getByTestId("clauses-not-decided")).toHaveTextContent("39 of the 40 that apply");
    expect(screen.queryByTestId("clauses-unchecked-share")).toBeNull();
    expect(screen.getByTestId("clauses-coverage-pair")).toHaveTextContent("1 of 40");
    expect(screen.queryByTestId("clauses-coverage-line")).toBeNull();
    expect(document.body.textContent).not.toContain("1 of 44");
  });

  it("switch on: a null boundary prints not recorded, never 0", () => {
    show({ coverage_pair: { ...pair, applicable: null, unknown: null } });
    const line = screen.getByTestId("clauses-not-decided");
    expect(line).not.toHaveTextContent("0 of");
    expect(line).toHaveTextContent(/not recorded/i);
  });

  it("switch on: a stored count that does not add up is still said", () => {
    show({ coverage_pair: pair, clause_coverage: { ...clause, adds_up: false } });
    expect(screen.getByTestId("clauses-coverage-pair")).toHaveTextContent("do not add up");
  });

  it("switch off: the old words and the stored line stay", () => {
    show({ coverage_pair: null });
    expect(screen.getByTestId("clauses-checked")).toHaveTextContent("30");
    expect(screen.getByTestId("clauses-unchecked-share")).toHaveTextContent("25%");
    expect(screen.getByTestId("clauses-coverage-line")).toHaveTextContent("1 of 44");
    expect(screen.queryByTestId("clauses-decided")).toBeNull();
  });
});
