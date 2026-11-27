/** A rough draft from the local model is downloaded only after the engineer's explicit OK (lead-5, 27 Nov 2026). Invented values. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { type GeneralReview, generalReview } from "../../../api/generalReview";
import { GeneralResults } from "./GeneralResults";

function review(over: Partial<GeneralReview> = {}): GeneralReview {
  return {
    paper_document_id: "doc_inv", run_id: "run_inv", method: "aim-1", mark: "AI, to be checked", status: "completed",
    identity: { kind: "datasheet", equipment_type: null, subject: null },
    counts: { points: 3, comments: 2, by_label: {}, boundary: "this paper, this review" },
    comments: [], points: [], books: [], not_held: [], unlisted_books: { count: 0, sentence: null },
    checklist: { key: null, items: null, reused: null, built_from: null },
    cost: { usd: null }, completeness: { ok: true, page: 3, database: 3, file_rows: 3, sentence: null },
    ...over,
  } as GeneralReview;
}
const signed = { state: "signed", undecided: [], undecided_count: 0, codes: ["Approved"], can_sign: false, may_sign: true, may_sign_words: null,
  signed: { by: "Invented Engineer", at: "2026-11-27T10:00:00Z", code: "Approved", statement: null, copy_statement: "x" } } as unknown as GeneralReview["signoff"];

let sheet: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  sheet = vi.spyOn(generalReview, "sheet").mockResolvedValue({ ok: true, data: { blob: new Blob(["x"]), filename: "f.xlsx" } } as never);
  vi.spyOn(generalReview, "history").mockResolvedValue({ ok: true, data: { paper_document_id: "doc_inv", boundary: "x", runs: [] } } as never);
  Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() });
});
afterEach(() => vi.restoreAllMocks());

const press = () => fireEvent.click(screen.getByTestId("general-download"));

describe("the team file of a rough draft from the local model", () => {
  it("asks first, and downloads only after 'I will check every comment'", async () => {
    render(<GeneralResults review={review({ engine: { local: true } })} howTab={null} onViewPage={() => undefined} />);
    press();
    expect(screen.getByTestId("general-rough-confirm")).toHaveTextContent("rough draft by the AI on this computer");
    expect(sheet).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("general-rough-ok"));
    await waitFor(() => expect(sheet).toHaveBeenCalledWith("doc_inv", "run_inv", "team", true));
  });

  it("Cancel downloads nothing", () => {
    render(<GeneralResults review={review({ engine: { local: true } })} howTab={null} onViewPage={() => undefined} />);
    press();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("general-rough-confirm")).toBeNull();
    expect(sheet).not.toHaveBeenCalled();
  });

  it("a Claude review and a SIGNED rough draft download at once, as before", async () => {
    const { unmount } = render(<GeneralResults review={review()} howTab={null} onViewPage={() => undefined} />);
    press();
    await waitFor(() => expect(sheet).toHaveBeenCalledWith("doc_inv", "run_inv", "team", false));
    unmount();
    sheet.mockClear();
    render(<GeneralResults review={review({ engine: { local: true }, signoff: signed })} howTab={null} onViewPage={() => undefined} />);
    press();
    expect(screen.queryByTestId("general-rough-confirm")).toBeNull();
    await waitFor(() => expect(sheet).toHaveBeenCalledWith("doc_inv", "run_inv", "team", false));
  });
});
