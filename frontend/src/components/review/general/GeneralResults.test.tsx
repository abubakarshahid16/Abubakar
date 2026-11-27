/** The results page says plainly when a checking step did not run (a failed AI step is shown in the run). Invented values only. */
import { fireEvent, render, screen } from "@testing-library/react";
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
/** E5 (answer first, 26 Nov 2026): run details live under the "How this review was made" tab. */
const openHow = () => fireEvent.click(screen.getByRole("tab", { name: "How this review was made" }));

describe("GeneralResults: steps that did not run", () => {
  it("shows each sentence plainly, above the counts, when a step did not run", () => {
    mount(review({ steps_not_applied: [
      { step: "aim_second_read", why: "no_json", sentence: "The second reader did not run on this sheet (no_json): invented." },
      { step: "aim_edit", why: "timeout", sentence: "The editor did not run on this sheet (timeout)." },
    ] }));
    expect(screen.getByTestId("general-steps-pointer")).toHaveTextContent("2 checking steps did not run: see How this review was made.");  // visible at the top (E5)
    expect(screen.queryByTestId("general-steps-not-applied")).toBeNull();  // the detail is folded (E5)
    openHow();
    expect(screen.getByTestId("how-summary")).toHaveTextContent("2 checking steps did not run.");  // said in the summary, first
    expect(screen.queryByTestId("general-steps-not-applied")).toBeNull();  // no panel is open at the start
    fireEvent.click(screen.getByRole("button", { name: /Second look at the faults/ }));
    const note = screen.getByTestId("general-steps-not-applied");
    expect(note).toHaveTextContent("2 checking steps did not run on this sheet.");
    expect(note).toHaveTextContent("The second reader did not run on this sheet (no_json): invented.");
    expect(note).toHaveTextContent("The editor did not run on this sheet (timeout).");
  });

  it("shows nothing when the list is empty or absent (an older answer)", () => {
    const { unmount } = mount(review({ steps_not_applied: [] }));
    openHow();
    expect(screen.queryByTestId("general-steps-not-applied")).toBeNull();
    expect(screen.queryByTestId("general-steps-pointer")).toBeNull();
    unmount();
    mount(review());
    openHow();
    expect(screen.queryByTestId("general-steps-not-applied")).toBeNull();
  });
});

describe("GeneralResults: a link stays a link (look gate, 27 Nov 2026)", () => {
  it("keeps 'see How this review was made', a link inside a sentence, as the kit link, never a boxed kit button", () => {
    mount(review({ steps_not_applied: [{ step: "aim_edit", why: "timeout", sentence: "The editor did not run on this sheet (timeout)." }] }));
    const link = screen.getByRole("button", { name: "see How this review was made" });
    expect(link.className).toContain("kit-link");
    expect(link.className).not.toContain("kit-btn");
  });
});

describe("GeneralResults: points decided by code", () => {
  it("shows the count with its denominator when the review has points, and nothing for an older answer", () => {
    const sentence = "2 of 5 points decided by code (code compared the paper's value with the rule's limit); the other 3 are AI readings, AI opinions or questions (this paper, this review).";
    const { unmount } = mount(review({ counts: { points: 5, comments: 1, by_label: {}, boundary: "this paper, this review",
      decided_by_code: { count: 2, of: 5, sentence } } }));
    openHow();  // E5: the counts are folded under "How this review was made"
    expect(screen.getByTestId("general-counts")).toHaveTextContent(sentence);
    unmount();
    mount(review());
    openHow();
    expect(screen.getByTestId("general-counts")).not.toHaveTextContent("decided by code");
  });

  it("lists a comment rejected before on its own team-only line with its note, and draws nothing when there is none", () => {
    const note = "rejected before on 2026-11-20, reason: The datasheet answers it on page 3; not a finding.";
    const moved = { n: 9, title: "Invented title", field: "Invented field", rejected_before: { note, day: "2026-11-20", reason: "x" } };
    const { unmount } = mount(review({ rejected_before: [moved] as unknown as GeneralReview["rejected_before"] }));
    expect(screen.getByTestId("general-rejected-before")).toHaveTextContent("Rejected before (1), team only");
    expect(screen.getByTestId("general-rejected-before")).toHaveTextContent(note);
    unmount();
    mount(review());
    expect(screen.queryByTestId("general-rejected-before")).toBeNull();
  });
});

