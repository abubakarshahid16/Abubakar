/** The results page says plainly when a checking step did not run (a failed AI step is shown in the run). Invented values only. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GeneralReview } from "../../../api/generalReview";
import { GeneralResults } from "./GeneralResults";

function review(over: Partial<GeneralReview> = {}): GeneralReview {
  return {
    paper_document_id: "doc1", run_id: "g1", method: "aim-1", mark: "AI, to be checked", status: "completed",
    identity: { kind: "datasheet", equipment_type: null, subject: null },
    counts: { points: 0, comments: 0, by_label: {}, boundary: "this paper, this review" },
    comments: [], points: [], books: [], not_held: [], unlisted_books: { count: 0, sentence: null },
    checklist: { key: null, items: null, reused: null, built_from: null },
    cost: { usd: null }, completeness: { ok: true, page: 0, database: 0, file_rows: 0, sentence: null },
    ...over,
  } as GeneralReview;
}
const mount = (r: GeneralReview) => render(<GeneralResults review={r} howTab={null} onViewPage={() => undefined} />);

describe("GeneralResults: steps that did not run", () => {
  it("shows each sentence plainly, above the counts, when a step did not run", () => {
    mount(review({ steps_not_applied: [
      { step: "aim_second_read", why: "no_json", sentence: "The second reader did not run on this sheet (no_json): invented." },
      { step: "aim_edit", why: "timeout", sentence: "The editor did not run on this sheet (timeout)." },
    ] }));
    const note = screen.getByTestId("general-steps-not-applied");
    expect(note).toHaveTextContent("A checking step did not run on this sheet.");
    expect(note).toHaveTextContent("The second reader did not run on this sheet (no_json): invented.");
    expect(note).toHaveTextContent("The editor did not run on this sheet (timeout).");
    expect(note.compareDocumentPosition(screen.getByTestId("general-counts")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows nothing when the list is empty or absent (an older answer)", () => {
    const { unmount } = mount(review({ steps_not_applied: [] }));
    expect(screen.queryByTestId("general-steps-not-applied")).toBeNull();
    unmount();
    mount(review());
    expect(screen.queryByTestId("general-steps-not-applied")).toBeNull();
  });
});
