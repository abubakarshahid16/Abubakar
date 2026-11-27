/** The sign-off bar of a general review (order 14). Invented values only. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const acceptRest = vi.fn();
const signOff = vi.fn();
const download = vi.fn();
vi.mock("../../../api/generalReview", async (orig) => ({
  ...(await orig<typeof import("../../../api/generalReview")>()),
  generalReview: { acceptRest: (...a: unknown[]) => acceptRest(...a), signOff: (...a: unknown[]) => signOff(...a) },
  downloadGeneralSheet: (...a: unknown[]) => download(...a),
}));

import type { GeneralReview, SignoffStatus } from "../../../api/generalReview";
import { SignBar } from "./SignBar";

const CODES = ["Approved", "Approved with Comments", "Rejected / Revise and Resubmit", "Manual Review Required"];
const review = { paper_document_id: "doc1", run_id: "run1" } as unknown as GeneralReview;
const status = (over: Partial<SignoffStatus> = {}): SignoffStatus => ({
  state: "not_signed", undecided: [], undecided_count: 0, codes: CODES, can_sign: true, may_sign: true, may_sign_words: null, signed: null, ...over,
});
const signed = { by: "Dana Engineer", at: "2026-11-18T12:00:00+00:00", code: "Approved with Comments", statement: "Checked it.", copy_statement: "6 points reviewed, 4 in this file, 2 not issued: 2 rejected by the engineer" };

function mount(s: SignoffStatus, extra: { onStatus?: () => void; onChanged?: () => void } = {}) {
  render(<SignBar review={review} signoff={s} onStatus={extra.onStatus ?? vi.fn()} onChanged={extra.onChanged ?? vi.fn()} />);
}

beforeEach(() => { acceptRest.mockReset(); signOff.mockReset(); download.mockReset(); });

describe("SignBar", () => {
  it("says how many comments still need a decision; Sign off stays off until all are decided and a code is chosen", () => {
    mount(status({ undecided_count: 2, undecided: [{ part: "comment", n: 3, title: "T3" }, { part: "comment", n: 5, title: "T5" }], can_sign: false }));
    expect(screen.getByTestId("sign-undecided")).toHaveTextContent("2 comments still need your decision.");
    expect(screen.getByTestId("sign-button")).toBeDisabled();
  });

  it("counts comments and points to confirm apart, never as one number of 'comments' (rule 4; C's re-measure)", () => {
    const undecided = [
      ...Array.from({ length: 11 }, (_, i) => ({ part: "comment" as const, n: i + 1, title: `C${i}` })),
      ...Array.from({ length: 7 }, (_, i) => ({ part: "confirmation" as const, n: i + 1, title: `P${i}` })),
    ];
    mount(status({ undecided_count: 18, undecided }));
    expect(screen.getByTestId("sign-undecided")).toHaveTextContent("11 comments and 7 points to confirm still need your decision.");
    expect(screen.getByRole("button", { name: "Accept the rest (11 comments and 7 points to confirm)" })).toBeTruthy();
  });

  it("a reader who is not a super user sees the sentence, no sign controls, no Accept the rest and no contractor download", () => {
    const words = "Only a super user can sign this review for now.";
    const { unmount } = render(<SignBar review={review} signoff={status({ undecided_count: 1, may_sign: false, may_sign_words: words })} onStatus={vi.fn()} onChanged={vi.fn()} />);
    expect(screen.getByTestId("sign-super-user")).toHaveTextContent(words);
    expect(screen.queryByTestId("sign-button")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Accept the rest/ })).toBeNull(); // it decides everything at once: the super user's
    unmount();
    mount(status({ state: "signed", signed, may_sign: false, may_sign_words: words }));
    expect(screen.queryByTestId("contractor-download")).toBeNull();
    expect(screen.getByTestId("sign-super-user")).toHaveTextContent(words);
  });

  it("the review code is the engineer's own choice: none is preselected and all four are offered", () => {
    mount(status());
    const select = screen.getByLabelText("Review code") as HTMLSelectElement;
    expect(select.value).toBe("");
    expect(Array.from(select.options).map((o) => o.text)).toEqual(["Choose the review code", ...CODES]);
    expect(screen.getByTestId("sign-button")).toBeDisabled();
    fireEvent.change(select, { target: { value: "Approved" } });
    expect(screen.getByTestId("sign-button")).toBeEnabled();
  });

  it("Accept the rest asks the server and tells the page to read the review again", async () => {
    acceptRest.mockResolvedValue({ ok: true, data: { run_id: "run1", accepted: 2 } });
    const onChanged = vi.fn();
    mount(status({ undecided_count: 2, can_sign: false }), { onChanged });
    fireEvent.click(screen.getByRole("button", { name: /^Accept the rest/ }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(acceptRest).toHaveBeenCalledWith("doc1", "run1");
  });

  it("signs with the chosen code and the statement, and hands the new status to the page", async () => {
    signOff.mockResolvedValue({ ok: true, data: { run_id: "run1", signoff: status({ state: "signed", signed }) } });
    const onStatus = vi.fn();
    mount(status(), { onStatus });
    fireEvent.change(screen.getByLabelText("Review code"), { target: { value: "Approved with Comments" } });
    fireEvent.change(screen.getByLabelText(/One line for the record/), { target: { value: " Checked it. " } });
    fireEvent.click(screen.getByTestId("sign-button"));
    await waitFor(() => expect(onStatus).toHaveBeenCalled());
    expect(signOff).toHaveBeenCalledWith("doc1", { run_id: "run1", review_code: "Approved with Comments", statement: "Checked it." });
  });

  it("a refusal is shown in the server's words with the comments that stand in the way", async () => {
    signOff.mockResolvedValue({ ok: false, error: { code: "crs_not_finished", message: "the contractor copy cannot be issued yet: comment 1: x",
      blockers: [{ part: "comment", n: 1, why: "its text carries a document id: edit it or reject it" }] } });
    mount(status());
    fireEvent.change(screen.getByLabelText("Review code"), { target: { value: "Approved" } });
    fireEvent.click(screen.getByTestId("sign-button"));
    const box = await screen.findByTestId("sign-refusal");
    expect(box).toHaveTextContent("the contractor copy cannot be issued yet");
    expect(box).toHaveTextContent("comment 1: its text carries a document id");
  });

  it("a 401 says to sign in", async () => {
    signOff.mockResolvedValue({ ok: false, error: { code: "unauthenticated", message: "sign in to continue" } });
    mount(status());
    fireEvent.change(screen.getByLabelText("Review code"), { target: { value: "Approved" } });
    fireEvent.click(screen.getByTestId("sign-button"));
    expect(await screen.findByTestId("sign-problem")).toHaveTextContent("Sign in to sign off this review.");
  });

  it("signed: says who, when, the code and the contractor copy's points statement, and offers the contractor download", async () => {
    download.mockResolvedValue(null);
    mount(status({ state: "signed", signed }));
    expect(screen.getByTestId("sign-signed")).toHaveTextContent("Signed off by Dana Engineer");
    expect(screen.getByTestId("sign-signed")).toHaveTextContent("Review code: Approved with Comments.");
    expect(screen.getByTestId("sign-copy-statement")).toHaveTextContent("6 points reviewed, 4 in this file, 2 not issued");
    expect(screen.queryByTestId("sign-button")).toBeNull();
    fireEvent.click(screen.getByTestId("contractor-download"));
    await waitFor(() => expect(download).toHaveBeenCalledWith("doc1", "run1", "contractor"));
  });

  it("changed since sign-off: a warning, no contractor download, and Sign off again", () => {
    mount(status({ state: "changed", signed }));
    expect(screen.getByTestId("sign-changed")).toHaveTextContent("Changed since sign-off.");
    expect(screen.queryByTestId("contractor-download")).toBeNull();
    expect(screen.getByTestId("sign-button")).toHaveTextContent("Sign off again");
  });

  it("offers no Accept the rest on a rough draft from the local model and says why; each comment is decided one by one", () => {
    const words = "This review is a rough draft from the local model: decide each comment one by one. There is no Accept the rest.";
    mount(status({ undecided_count: 3, bulk_accept: false, rough_draft_words: words }));
    expect(screen.queryByRole("button", { name: /Accept the rest/ })).toBeNull();
    expect(screen.getByTestId("sign-rough-draft")).toHaveTextContent(words);
  });

  it("keeps Accept the rest on a Claude review", () => {
    mount(status({ undecided_count: 3, bulk_accept: true, rough_draft_words: null }));
    expect(screen.getByRole("button", { name: "Accept the rest (3 items)" })).toBeInTheDocument(); // kinds not listed: said as items, never as comments
    expect(screen.queryByTestId("sign-rough-draft")).toBeNull();
  });

  it("says a sign-off was made from a rough draft", () => {
    mount(status({ state: "signed", signed: { ...signed, rough_draft: "made from a rough draft (local model)" } }));
    expect(screen.getByTestId("sign-made-from")).toHaveTextContent("Sign-off made from a rough draft (local model).");
  });
});
