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
const exportCrs = vi.fn();
const setCrsTransmittals = vi.fn();

vi.mock("../api/client", () => ({
  api: {},
  reviews: {
    reviewRuns: (...args: unknown[]) => reviewRuns(...args),
    exportCrs: (...args: unknown[]) => exportCrs(...args),
    setCrsTransmittals: (...args: unknown[]) => setCrsTransmittals(...args),
  },
}));

import { ReviewCrsList } from "./ReviewCrsList";
import { CrsTransmittalsForm } from "./ReviewRunsView";

beforeEach(() => {
  reviewRuns.mockReset();
  exportCrs.mockReset();
  setCrsTransmittals.mockReset();
});

describe("ReviewCrsList", () => {
  it("lists each run and downloads its CRS", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [
      { review_run_id: "run-1", submittal_document_id: "d1", submittal_filename: "psv-sheet.pdf",
        status: "completed", created_at: "2026-10-02T10:00:00Z" },
    ] } });
    exportCrs.mockResolvedValue({ ok: false, error: { message: "offline" } });
    render(<ReviewCrsList />);
    expect(reviewRuns).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /show the review runs/i }));
    expect(await screen.findByText("psv-sheet.pdf")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /download crs/i }));
    expect(exportCrs).toHaveBeenCalledWith("run-1", "internal");
    expect(await screen.findByRole("alert")).toBeTruthy();
  });

  it("says when there are no runs", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: [] } });
    render(<ReviewCrsList />);
    await userEvent.click(screen.getByRole("button", { name: /show the review runs/i }));
    expect(await screen.findByText(/no review runs/i)).toBeTruthy();
  });
});

describe("CrsTransmittalsForm", () => {
  it("saves what was typed and refreshes the sheet", async () => {
    setCrsTransmittals.mockResolvedValue({ ok: true, data: { company_transmittal: "CT-1", contractor_transmittal: "" } });
    const onChanged = vi.fn();
    render(<CrsTransmittalsForm runId="run-1" onChanged={onChanged}
      header={[{ label: "COMPANY Transmittal No.:", value: "" }, { label: "CONTRACTOR  Transmittal No.:", value: "XT-9" }]} />);
    const company = screen.getByLabelText(/company transmittal no/i);
    expect((screen.getByLabelText(/contractor transmittal no/i) as HTMLInputElement).value).toBe("XT-9");
    await userEvent.type(company, "CT-1");
    await userEvent.click(screen.getByRole("button", { name: /save transmittal numbers/i }));
    expect(setCrsTransmittals).toHaveBeenCalledWith("run-1", { company_transmittal: "CT-1", contractor_transmittal: "XT-9" });
    expect(onChanged).toHaveBeenCalled();
    expect(await screen.findByRole("status")).toBeTruthy();
  });
});
