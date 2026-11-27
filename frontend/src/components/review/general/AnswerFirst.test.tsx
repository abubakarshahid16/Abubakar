/** E5, ANSWER FIRST (owner's G9 "easy to use", 26 Nov 2026): the review page opens on the verdict line ("N comments need your
 *  decision") and the comments; run details, model notes and steps that did not run are folded under "How this review was made",
 *  with a one-line pointer for anything that did not run or was not read. Invented values only. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GeneralReview } from "../../../api/generalReview";
import { GeneralResults, verdict } from "./GeneralResults";

function review(over: Partial<GeneralReview> = {}): GeneralReview {
  return {
    paper_document_id: "doc1", run_id: "g1", method: "aim-1", mark: "AI, to be checked", status: "completed",
    identity: { kind: "datasheet", equipment_type: null, subject: null },
    counts: { points: 12, comments: 5, by_label: {}, boundary: "this paper, this review" },
    comments: [], points: [], books: [], not_held: [], unlisted_books: { count: 0, sentence: null },
    checklist: { key: null, items: null, reused: null, built_from: null },
    cost: { usd: 1.25 }, completeness: { ok: true, page: 12, database: 12, file_rows: 12, sentence: null },
    ...over,
  } as GeneralReview;
}
const status = (state: string, undecided_count: number) =>
  ({ state, undecided: [], undecided_count, codes: [], can_sign: false, may_sign: true, may_sign_words: null, signed: null }) as unknown as GeneralReview["signoff"];

describe("answer first", () => {
  it("the verdict line says how many comments need a decision, or that all are decided, or the sign-off", () => {
    expect(verdict(review(), status("not_signed", 3))).toBe("3 comments need your decision.");
    expect(verdict(review(), status("not_signed", 1))).toBe("1 comment needs your decision.");
    expect(verdict(review(), status("not_signed", 0))).toBe("All comments are decided: ready to sign off.");
    expect(verdict(review(), status("signed", 0))).toBe("5 comments decided."); // "Signed off" is said once, as the box's label
    expect(verdict(review(), status("changed", 0))).toBe("Changed since sign-off: sign it off again before the contractor copy.");
    expect(verdict(review(), null)).toBe("5 comments to check (12 points reviewed).");
  });

  it("opens on the verdict and the comments; model notes, counts and cost are folded under How this review was made", () => {
    render(<GeneralResults review={review({ signoff: status("not_signed", 2) })} howTab={null} onViewPage={() => undefined} />);
    expect(screen.getByTestId("general-verdict")).toHaveTextContent("2 comments need your decision.");
    expect(screen.getByTestId("general-mark")).toHaveTextContent("AI, to be checked");  // the mark stays on the header
    expect(screen.getByRole("tab", { name: "Comments (5)" })).toHaveAttribute("aria-selected", "true");
    for (const id of ["general-counts", "general-cost"]) expect(screen.queryByTestId(id)).toBeNull();  // folded (E5)
    fireEvent.click(screen.getByRole("tab", { name: "How this review was made" }));
    expect(screen.getByTestId("general-counts")).toHaveTextContent("12 points were checked against");
    expect(screen.queryByTestId("how-panel")).toBeNull();  // no panel is open at the start (owner, 28 Nov 2026)
    expect(screen.getByTestId("how-time")).toHaveTextContent("USD 1.25");  // the cost is folded at the foot
  });

  it("the pointer to a step that did not run opens How this review was made", () => {
    render(<GeneralResults review={review({ steps_not_applied: [{ step: "aim_edit", why: "timeout", sentence: "The editor did not run (timeout)." }] })}
      howTab={null} onViewPage={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "see How this review was made" }));
    expect(screen.getByTestId("how-summary")).toHaveTextContent("1 checking step did not run.");
    fireEvent.click(screen.getByRole("button", { name: /Second look at the faults/ }));
    expect(screen.getByTestId("general-steps-not-applied")).toHaveTextContent("The editor did not run (timeout).");
  });
});
