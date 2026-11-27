/**
 * #725 F7: the "CRS & Reports" page lists each review run's CRS, and the
 * CRS preview's transmittal numbers are entered by an engineer.
 *
 * MUTATION PROOF: render nothing from ReviewCrsList and "lists each run"
 * fails; drop the setCrsTransmittals call and "saves what was typed" fails.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const reviewRuns = vi.fn();
const reviewRunsPage = vi.fn();
const exportCrs = vi.fn();
const setCrsTransmittals = vi.fn();

vi.mock("../api/client", () => ({
  api: {},
  reviews: {
    reviewRuns: (...args: unknown[]) => reviewRuns(...args),
    reviewRunsPage: (...args: unknown[]) => reviewRunsPage(...args),
    exportCrs: (...args: unknown[]) => exportCrs(...args),
    setCrsTransmittals: (...args: unknown[]) => setCrsTransmittals(...args),
  },
}));

import { RUNS_PAGE, ReviewCrsList } from "./ReviewCrsList";
import { CrsTransmittalsForm } from "../components/review/CrsPreviewSheet";
import { NEW_LOOK } from "../look";

/** The new look says "reviews" where the classic look says "review runs" (everyday words, E3). */
const RUNS_WORD = NEW_LOOK ? "reviews" : "review runs";

beforeEach(() => {
  reviewRuns.mockReset();
  reviewRunsPage.mockReset();
  exportCrs.mockReset();
  setCrsTransmittals.mockReset();
});

describe("ReviewCrsList", () => {
  it.runIf(NEW_LOOK)("says a shared state and what each file is once, and each row's button is one word (C's walk, 27 Nov 2026)", async () => {
    const run = (id: string, file: string) => ({ review_run_id: id, submittal_document_id: "d-" + id, submittal_filename: file, status: "completed", created_at: "2026-10-02T10:00:00Z" });
    reviewRunsPage.mockResolvedValue({ ok: true, data: { total: 2, limit: RUNS_PAGE, offset: 0, runs: [run("r1", "invented-a.pdf"), run("r2", "invented-b.pdf")] } });
    render(<ReviewCrsList />);
    // the new look lists them at once (the classic look waits for "Show"); the one word keeps its full name for screen readers
    const button = await screen.findByRole("button", { name: "Download CRS (internal review copy) of invented-a.pdf" });
    expect(button.textContent).toBe("Download");
    expect(screen.getByTestId("crs-said-once").textContent).toBe("Every review below is completed; each file is the internal review copy.");
    expect(screen.queryByText(/^completed/)).toBeNull();
  });

  it("lists each run and downloads its CRS", async () => {
    reviewRunsPage.mockResolvedValue({ ok: true, data: { total: 1, limit: RUNS_PAGE, offset: 0, runs: [
      { review_run_id: "run-1", submittal_document_id: "d1", submittal_filename: "psv-sheet.pdf",
        status: "completed", created_at: "2026-10-02T10:00:00Z" },
    ] } });
    exportCrs.mockResolvedValue({ ok: false, error: { message: "offline" } });
    render(<ReviewCrsList />);
    expect(reviewRunsPage).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /show the review runs/i }));
    expect(await screen.findByText("psv-sheet.pdf")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /download crs/i }));
    expect(exportCrs).toHaveBeenCalledWith("run-1", "internal");
    expect(await screen.findByRole("alert")).toBeTruthy();
  });

  it("says when there are no runs", async () => {
    reviewRunsPage.mockResolvedValue({ ok: true, data: { runs: [], total: 0, limit: RUNS_PAGE, offset: 0 } });
    render(<ReviewCrsList />);
    await userEvent.click(screen.getByRole("button", { name: /show the review runs/i }));
    expect(await screen.findByText(NEW_LOOK ? /no reviews on documents you can read/i : /no review runs/i)).toBeTruthy();
  });
});

describe("ReviewCrsList pages (#1131)", () => {
  const run = (i: number) => ({ review_run_id: `run-${i}`, submittal_document_id: `d${i}`,
    submittal_filename: `sheet-${i}.pdf`, status: "completed", created_at: "2026-10-02T10:00:00Z" });

  it("asks for one page, says how many of how many, and adds the next page on Show more", async () => {
    reviewRunsPage.mockImplementation(async (offset: number, limit: number) => ({ ok: true, data: {
      total: 3, limit, offset, runs: [run(1), run(2), run(3)].slice(offset, offset + 2) } }));
    render(<ReviewCrsList />);
    await userEvent.click(screen.getByRole("button", { name: /show the review runs/i }));
    expect(await screen.findByTestId("crs-runs-count")).toHaveTextContent(`Showing 2 of 3 ${RUNS_WORD} on submittals you can read`);
    expect(reviewRunsPage).toHaveBeenCalledWith(0, RUNS_PAGE);
    expect(reviewRuns).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(await screen.findByText("sheet-3.pdf")).toBeTruthy();
    expect(reviewRunsPage).toHaveBeenLastCalledWith(2, RUNS_PAGE);
    expect(screen.getByTestId("crs-runs-count")).toHaveTextContent(`Showing 3 of 3 ${RUNS_WORD} on submittals you can read`);
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("never lists a run twice when the list moved between pages", async () => {
    reviewRunsPage
      .mockResolvedValueOnce({ ok: true, data: { total: 3, limit: 2, offset: 0, runs: [run(1), run(2)] } })
      .mockResolvedValueOnce({ ok: true, data: { total: 3, limit: 2, offset: 2, runs: [run(2), run(3)] } });
    render(<ReviewCrsList />);
    await userEvent.click(screen.getByRole("button", { name: /show the review runs/i }));
    await userEvent.click(await screen.findByRole("button", { name: "Show more" }));
    expect(await screen.findByText("sheet-3.pdf")).toBeTruthy();
    expect(screen.getAllByText("sheet-2.pdf")).toHaveLength(1);
  });

  it("does not skip a run when runs were deleted between pages", async () => {
    // Page 1 showed run-1, run-2 of 4; run-1 is then deleted, so run-3 moves
    // to offset 1 and reading on from offset 2 would skip it.
    reviewRunsPage
      .mockResolvedValueOnce({ ok: true, data: { total: 4, limit: 2, offset: 0, runs: [run(1), run(2)] } })
      .mockResolvedValueOnce({ ok: true, data: { total: 3, limit: 2, offset: 2, runs: [run(4)] } })
      .mockResolvedValueOnce({ ok: true, data: { total: 3, limit: 3, offset: 1, runs: [run(3), run(4)] } });
    render(<ReviewCrsList />);
    await userEvent.click(screen.getByRole("button", { name: /show the review runs/i }));
    await userEvent.click(await screen.findByRole("button", { name: "Show more" }));
    expect(await screen.findByText("sheet-3.pdf")).toBeTruthy();
    expect(reviewRunsPage).toHaveBeenLastCalledWith(1, RUNS_PAGE + 1);
    expect(screen.getAllByText("sheet-4.pdf")).toHaveLength(1);
  });
});

describe("CrsTransmittalsForm", () => {
  it("saves what was typed and refreshes the sheet", async () => {
    setCrsTransmittals.mockResolvedValue({ ok: true, data: { company_transmittal: "CT-1", contractor_transmittal: "" } });
    const onChanged = vi.fn();
    render(<CrsTransmittalsForm runId="run-1" onChanged={onChanged}
      header={[{ label: "COMPANY Transmittal No.:", value: "" }, { label: "CONTRACTOR  Transmittal No.:", value: "XT-9" }]} />);
    const company = screen.getByLabelText(/company transmittal number/i);
    expect((screen.getByLabelText(/contractor transmittal number/i) as HTMLInputElement).value).toBe("XT-9");
    await userEvent.type(company, "CT-1");
    await userEvent.click(screen.getByRole("button", { name: /save transmittal numbers/i }));
    expect(setCrsTransmittals).toHaveBeenCalledWith("run-1", { company_transmittal: "CT-1", contractor_transmittal: "XT-9" });
    expect(onChanged).toHaveBeenCalled();
    expect(await screen.findByRole("status")).toBeTruthy();
  });
  it.runIf(NEW_LOOK)("a clear majority is said once and only a row that differs keeps its state", async () => {
    const run = (id: string, status: string) => ({ review_run_id: id, submittal_document_id: "d-" + id, submittal_filename: id + ".pdf", status, created_at: "2026-10-02T10:00:00Z" });
    reviewRunsPage.mockResolvedValue({ ok: true, data: { total: 3, limit: RUNS_PAGE, offset: 0, runs: [run("r1", "completed"), run("r2", "completed"), run("r3", "failed")] } });
    render(<ReviewCrsList />);
    expect((await screen.findByTestId("crs-said-once")).textContent).toBe("Every review below is completed unless its row says otherwise; each file is the internal review copy.");
    expect(screen.getAllByText(/^failed/)).toHaveLength(1);
    expect(screen.queryByText(/^completed/)).toBeNull();
  });
});

