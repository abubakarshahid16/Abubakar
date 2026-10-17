/**
 * #967 item 5: the datasheet pane asks the server to mark EVERY card's value
 * on the page shown, with each card's state - not only the selected card's.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ReviewFinding } from "../../../types/api";
import { DocumentPane } from "./DocumentPane";
import { type PageMark, buildCards, marksOn } from "./sheetCards";

const seen: { runId: string; page: number; marks: PageMark[] }[] = [];

vi.mock("./SheetPageImage", () => ({
  SheetPageImage: (props: { runId: string; page: number; marks: PageMark[] }) => {
    seen.push(props);
    return <p>{`marked page ${props.page}`}</p>;
  },
}));
vi.mock("../EvidencePageImage", () => ({ EvidencePageImage: () => <p>rule page</p> }));
vi.mock("../../DocumentPreview", () => ({ DocumentPreview: () => <p>plain page</p> }));

function finding(id: string, page: number, extra: Partial<ReviewFinding> = {}): ReviewFinding {
  return {
    id, document_id: "sub-1", origin: "comparison", compliance_status: "MISSING_INFORMATION",
    // a different sentence per finding, so each is its own card (same
    // template + same reason would collapse them into one)
    finding: `${id} is ${id.length} wrong`, required_action: `${id} is ${id.length} wrong`, contractor_page: page,
    contractor_section: id, ...extra,
  } as unknown as ReviewFinding;
}

describe("DocumentPane marks", () => {
  it("marks every card's value on the page, open amber and answered grey, and none from other pages", () => {
    const cards = buildCards([
      finding("set-pressure", 2),
      finding("orifice", 2, { confirmed_by: "eng", engineer_comment: "checked" }),
      finding("tag", 3),
    ]);
    expect(marksOn(cards, 2)).toEqual([
      { findingId: "set-pressure", state: "open" },
      { findingId: "orifice", state: "answered" },
    ]);
    expect(marksOn(cards, 3)).toEqual([{ findingId: "tag", state: "open" }]);
    expect(marksOn(cards, 1)).toEqual([]);
  });

  it("shows the run's marked page for a page with cards, the plain page otherwise", () => {
    seen.length = 0;
    const cards = buildCards([finding("set-pressure", 2), finding("orifice", 2, { confirmed_by: "eng", engineer_comment: "checked" })]);
    const submittal = { id: "sub-1", page_count: 3 } as never;
    const props = { runId: "run-9", submittal, cards, selected: cards[0], pulse: 0, onPage: () => {}, onSelectCard: () => {}, onCloseRule: () => {} };
    const { rerender } = render(<DocumentPane {...props} view={{ page: 2, rule: null }} />);
    expect(screen.getByText("marked page 2")).toBeInTheDocument();
    expect(seen.at(-1)).toMatchObject({ runId: "run-9", page: 2, marks: [
      { findingId: "set-pressure", state: "open" }, { findingId: "orifice", state: "answered" },
    ] });
    rerender(<DocumentPane {...props} view={{ page: 1, rule: null }} />);
    expect(screen.getByText("plain page")).toBeInTheDocument();
  });
});
