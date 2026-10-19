/**
 * Order 123 item 1: the click path. On the Submittals page, "New review",
 * then one file, and the review starts and opens: 2 clicks and a file,
 * where it used to be about 10 clicks over 3 pages.
 *
 * The upload itself (XMLHttpRequest) is the Documents page's Uploader and is
 * tested there; here it is replaced by a stand-in that reports one finished
 * upload, so the test is about what the page does next.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SubmittalsLandingView } from "./SubmittalsLandingView";

const documents = vi.fn();
const reviewRuns = vi.fn();
const startReviewRun = vi.fn();
const setRoleBulk = vi.fn();

vi.mock("../api/client", () => ({
  api: { documents: (...args: unknown[]) => documents(...args) },
  reviews: {
    reviewRuns: (...args: unknown[]) => reviewRuns(...args),
    startReviewRun: (...args: unknown[]) => startReviewRun(...args),
    reviewRunSummary: vi.fn(),
  },
  classification: { setRoleBulk: (...args: unknown[]) => setRoleBulk(...args) },
}));

let uploaded = { documentId: "doc-9", duplicateOf: null as string | null };
vi.mock("../components/Uploader", () => ({
  Uploader: ({ onFileDone, single }: {
    onFileDone?: (name: string, state: unknown) => void; single?: boolean;
  }) => (
    <button type="button" onClick={() => onFileDone?.("pump.pdf", {
      phase: "done", documentId: uploaded.documentId, duplicateOf: uploaded.duplicateOf, awaitingGrant: false,
    })}>
      {single ? "choose a file" : "choose files"}
    </button>
  ),
}));

const run = (id: string, documentId: string) => ({
  review_run_id: id, submittal_document_id: documentId, submittal_filename: "pump.pdf",
  equipment_tags: [], status: "completed", created_at: "2026-10-01T00:00:00Z",
  standards_in_scope: 1, findings_total: 0, by_status: {},
});

beforeEach(() => {
  for (const fn of [documents, reviewRuns, startReviewRun, setRoleBulk]) fn.mockReset();
  documents.mockResolvedValue({ ok: true, data: [] });
  reviewRuns.mockResolvedValue({ ok: true, data: { runs: [] } });
  setRoleBulk.mockImplementation(async ({ document_ids }: { document_ids: string[] }) => ({
    ok: true, data: { document_role: "CONTRACTOR_SUBMITTAL", requested: 1, updated: document_ids, unchanged: [], failed: [] },
  }));
  uploaded = { documentId: "doc-9", duplicateOf: null };
});

describe("New review on the Submittals page (order 123 item 1)", () => {
  it("marks the file a contractor submittal, starts its review and opens it", async () => {
    startReviewRun.mockResolvedValue({ ok: true, data: { review_run_id: "run-9" } });
    const onOpenRun = vi.fn();
    render(<SubmittalsLandingView onOpenRun={onOpenRun} inbox={false} />);
    await userEvent.click(await screen.findByRole("button", { name: "New review" }));
    await userEvent.click(screen.getByRole("button", { name: "choose a file" }));
    await vi.waitFor(() => expect(onOpenRun).toHaveBeenCalledWith("run-9"));
    expect(setRoleBulk).toHaveBeenCalledWith({ document_ids: ["doc-9"], document_role: "CONTRACTOR_SUBMITTAL" });
    expect(startReviewRun).toHaveBeenCalledWith("doc-9");
  });

  it("opens the existing review when the same file was reviewed before, without starting another", async () => {
    uploaded = { documentId: "", duplicateOf: "doc-1" };
    documents.mockResolvedValue({ ok: true, data: [{ id: "doc-1", filename: "pump.pdf", document_role: "CONTRACTOR_SUBMITTAL" }] });
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [run("run-1", "doc-1")] } });
    const onOpenRun = vi.fn();
    render(<SubmittalsLandingView onOpenRun={onOpenRun} inbox={false} />);
    await userEvent.click(await screen.findByRole("button", { name: "New review" }));
    await userEvent.click(screen.getByRole("button", { name: "choose a file" }));
    await vi.waitFor(() => expect(onOpenRun).toHaveBeenCalledWith("run-1"));
    expect(startReviewRun).not.toHaveBeenCalled();
  });

  it("does not start a review when the file could not be marked a submittal", async () => {
    setRoleBulk.mockResolvedValue({ ok: false, error: { code: "forbidden", message: "Administrators only." } });
    const onOpenRun = vi.fn();
    render(<SubmittalsLandingView onOpenRun={onOpenRun} inbox={false} />);
    await userEvent.click(await screen.findByRole("button", { name: "New review" }));
    await userEvent.click(screen.getByRole("button", { name: "choose a file" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be marked a contractor submittal: Administrators only.");
    expect(startReviewRun).not.toHaveBeenCalled();
    expect(onOpenRun).not.toHaveBeenCalled();
  });
});
