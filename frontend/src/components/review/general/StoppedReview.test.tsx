/** H's one-real-file pass (27 Nov 2026) on a review that STOPPED early with 0 points:
 *  R1 it said "All comments are decided: ready to sign off" and offered the sign-off form;
 *  R2 it gave no way to the paper's last COMPLETE review (only a History line);
 *  R5 the completeness check said "all three agree" for 0 / 0 / 0 (nothing was compared).
 *  Invented values only. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type GeneralReview, generalReview } from "../../../api/generalReview";
import { GeneralResults, cannotSignOff, verdict } from "./GeneralResults";
import { completenessResult } from "./HowReviewMade";

function review(over: Partial<GeneralReview> = {}): GeneralReview {
  return {
    paper_document_id: "doc_inv", run_id: "run_stopped", method: "aim-1", mark: "AI, to be checked", status: "completed",
    identity: { kind: "datasheet", equipment_type: null, subject: null },
    counts: { points: 12, comments: 5, by_label: {}, boundary: "this paper, this review" },
    comments: [], points: [], books: [], not_held: [], unlisted_books: { count: 0, sentence: null },
    checklist: { key: null, items: null, reused: null, built_from: null },
    cost: { usd: null }, completeness: { ok: true, page: 12, database: 12, file_rows: 12, sentence: null },
    ...over,
  } as GeneralReview;
}
const notSigned = { state: "not_signed", undecided: [], undecided_count: 0, codes: ["Approved"], can_sign: false, may_sign: true, may_sign_words: null, signed: null } as unknown as GeneralReview["signoff"];
const stopped = (over: Partial<GeneralReview> = {}) =>
  review({ status: "stopped", stop_reason: "invented stop", counts: { points: 0, comments: 0, by_label: {}, boundary: "this paper, this review" },
    completeness: { ok: false, page: 0, database: 0, file_rows: 0, sentence: "Nothing to compare: invented.", nothing_to_compare: true }, signoff: notSigned, ...over });

afterEach(() => vi.restoreAllMocks());

describe("R1: a stopped or empty review is never ready to sign off", () => {
  it("the verdict says there is nothing to sign off", () => {
    expect(verdict(stopped(), notSigned)).toBe("This review stopped before it finished: there is nothing to sign off.");
    expect(verdict(review({ counts: { points: 0, comments: 0, by_label: {}, boundary: "x" } }), notSigned))
      .toBe("No points were reviewed: there is nothing to sign off.");
    expect(verdict(review(), notSigned)).toBe("All comments are decided: ready to sign off."); // a finished review is unchanged
  });

  it("the sign-off form is not offered on a stopped review", () => {
    vi.spyOn(generalReview, "history").mockResolvedValue({ ok: true, data: { paper_document_id: "doc_inv", boundary: "x", runs: [] } } as never);
    render(<GeneralResults review={stopped()} howTab={null} onViewPage={() => undefined} />);
    expect(screen.getByTestId("general-verdict")).toHaveTextContent("there is nothing to sign off");
    expect(screen.queryByTestId("sign-button")).toBeNull();
    expect(screen.queryByTestId("general-download")).toBeNull(); // nothing to compare: no file to give out
    expect(cannotSignOff(stopped(), notSigned)).toBe(true);
    expect(cannotSignOff(review(), notSigned)).toBe(false);
  });

  it("a review already signed keeps its sign-off state", () => {
    const signed = { ...notSigned, state: "signed" } as unknown as GeneralReview["signoff"];
    expect(cannotSignOff(stopped(), signed)).toBe(false);
  });
});

describe("R2: a stopped review points to the last complete one", () => {
  it("names the last complete review with its points and opens it", async () => {
    vi.spyOn(generalReview, "history").mockResolvedValue({ ok: true, data: { paper_document_id: "doc_inv", boundary: "x", runs: [
      { run_id: "run_stopped", version: "general", part: "p", status: "stopped", started_at: null, finished_at: null, points: 0, files: [] },
      { run_id: "run_empty_done", version: "general", part: "p", status: "done", started_at: null, finished_at: "2026-11-10T10:00:00Z", points: 0, files: [] },
      { run_id: "run_complete", version: "general", part: "p", status: "done", started_at: null, finished_at: "2026-11-18T10:00:00Z", points: 116, files: [] },
    ] } } as never);
    const open = vi.fn();
    render(<GeneralResults review={stopped()} howTab={null} onViewPage={() => undefined} onOpenRun={open} />);
    await waitFor(() => expect(screen.getByTestId("general-last-complete")).toHaveTextContent("(116 points)"));
    expect(screen.getByTestId("general-last-complete")).toHaveTextContent("from 18 Nov 2026 (116 points)");
    fireEvent.click(screen.getByRole("button", { name: "open it" }));
    expect(open).toHaveBeenCalledWith("run_complete");
  });

  it("says nothing when there is no complete review, and nothing on a finished review", async () => {
    const spy = vi.spyOn(generalReview, "history").mockResolvedValue({ ok: true, data: { paper_document_id: "doc_inv", boundary: "x", runs: [] } } as never);
    const { unmount } = render(<GeneralResults review={stopped()} howTab={null} onViewPage={() => undefined} onOpenRun={vi.fn()} />);
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(screen.queryByTestId("general-last-complete")).toBeNull();
    unmount();
    spy.mockClear();
    render(<GeneralResults review={review({ signoff: notSigned })} howTab={null} onViewPage={() => undefined} onOpenRun={vi.fn()} />);
    expect(spy).not.toHaveBeenCalled();
    expect(screen.queryByTestId("general-last-complete")).toBeNull();
  });
});

describe("C's notes on #1981: first, one red, no 'points below' when there are none", () => {
  it("the last complete review comes before the stop line; 0/0/0 is a quiet note; no 'points below' with 0 points", async () => {
    vi.spyOn(generalReview, "history").mockResolvedValue({ ok: true, data: { paper_document_id: "doc_inv", boundary: "x", runs: [
      { run_id: "run_complete", version: "general", part: "p", status: "done", started_at: null, finished_at: "2026-11-18T10:00:00Z", points: 116, files: [] },
    ] } } as never);
    render(<GeneralResults review={stopped()} howTab={null} onViewPage={() => undefined} onOpenRun={vi.fn()} />);
    const last = await screen.findByTestId("general-last-complete");
    const stop = screen.getByTestId("general-stopped");
    expect(last.compareDocumentPosition(stop) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(stop).not.toHaveTextContent("points below");
    const incomplete = screen.getByTestId("general-incomplete");
    expect(incomplete.getAttribute("role")).toBeNull();
    expect(incomplete.querySelector("[role=alert]")).toBeNull();
    expect(incomplete).toHaveTextContent("Nothing to compare");
  });

  it("a stopped review WITH points still says the points below are the ones it reached", () => {
    vi.spyOn(generalReview, "history").mockResolvedValue({ ok: true, data: { paper_document_id: "doc_inv", boundary: "x", runs: [] } } as never);
    render(<GeneralResults review={stopped({ counts: { points: 4, comments: 2, by_label: {}, boundary: "x" }, completeness: { ok: true, page: 4, database: 4, file_rows: 4, sentence: null } })}
      howTab={null} onViewPage={() => undefined} />);
    expect(screen.getByTestId("general-stopped")).toHaveTextContent("The points below are the ones it reached.");
  });
});

describe("R5: three counts of 0 are nothing to compare, never 'all three agree'", () => {
  it("words the result", () => {
    expect(completenessResult({ ok: true, page: 0, database: 0, file_rows: 0, sentence: null })).toBe("nothing to compare: the review has no points");
    expect(completenessResult({ ok: false, page: 0, database: 0, file_rows: 0, sentence: "x", nothing_to_compare: true })).toBe("nothing to compare: the review has no points");
    expect(completenessResult({ ok: true, page: 3, database: 3, file_rows: 3, sentence: null })).toBe("all three agree");
    expect(completenessResult({ ok: false, page: 3, database: 2, file_rows: 3, sentence: "x" })).toBe("they differ: the file is refused");
  });
});
