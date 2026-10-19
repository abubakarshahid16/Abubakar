/**
 * Order 152.2: the box names the standard of each other item on the issued
 * copy (invented names), at most ten lines, and logs nothing.
 * MUTATION PROOF: print the kind words alone and "names the standard" fails;
 * drop the cap and "stops at ten" fails; log a name and "logs no name" fails.
 */
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CrsIssueGate, ReviewRunSummary } from "../../../types/api";
import { BeforeYouSign } from "./BeforeYouSign";

const run = { review_run_id: "run-1", engineer_final_code: "Code 2" } as unknown as ReviewRunSummary;

function mount(open: CrsIssueGate["open_findings"]) {
  const gate = {
    review_run_id: "run-1", issuable: false, final_code_recorded: true, blockers: [], unread_pages: [],
    checked_pages: [], pages_total: 4, open_findings: open,
  } as CrsIssueGate;
  render(<BeforeYouSign run={run} rows={[]} state={{ gate, error: null, reload: async () => {} }} onRunChanged={() => {}} onJump={() => {}} />);
}

afterEach(() => vi.restoreAllMocks());

describe("BeforeYouSign: other items", () => {
  it("names the standard of each item, and the kind alone when none was sent", () => {
    mount([
      { finding_id: "a", row_kind: "standard_not_cited", item: 1, standard: "STD-Q 7 clause 2" },
      { finding_id: "b", row_kind: "missing_reference", item: 2 },
    ]);
    const box = screen.getByTestId("sign-items");
    expect(box).toHaveTextContent("a standard the datasheet does not cite: STD-Q 7 clause 2");
    expect(box).toHaveTextContent("a standard that is not in the library");
    expect(screen.getByTestId("sign-left")).toHaveTextContent("decide 2 other items on the issued copy (1 standard not cited, 1 not in the library)");
  });

  it("stops at ten lines and says how many more", () => {
    mount(Array.from({ length: 13 }, (_, i) => ({ finding_id: `f${i}`, row_kind: "standard_not_cited", item: i, standard: `STD-Q ${i}` })));
    const box = screen.getByTestId("sign-items");
    expect(box.querySelectorAll("li")).toHaveLength(11);
    expect(box).toHaveTextContent("and 3 more of 13");
    expect(box).not.toHaveTextContent("STD-Q 12");
  });

  it("logs no standard name", () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) => vi.spyOn(console, m).mockImplementation(() => {}));
    mount([{ finding_id: "a", row_kind: "standard_not_cited", item: 1, standard: "STD-Q 7 clause 2" }]);
    for (const spy of spies) expect(JSON.stringify(spy.mock.calls)).not.toContain("STD-Q");
  });
});
