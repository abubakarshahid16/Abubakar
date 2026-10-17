/** #925 item 1: "Run AI review" is admin-gated on the server
 *  (`POST /api/reviews/run` 404s anyone else), but this view showed the
 *  launcher to everyone and its empty state told a non-admin to use it
 *  anyway - a dead end, not an instruction. */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewRunsView } from "./ReviewRunsView";

const documents = vi.fn();
const reviewRuns = vi.fn();
const startReviewRun = vi.fn();
vi.mock("../api/client", () => ({
  api: { documents: (...a: unknown[]) => documents(...a) },
  reviews: {
    reviewTrace: async () => ({ ok: false, error: { message: "not in this test" } }),
    readiness: async () => ({ ok: false, error: { message: "not in this test" } }),
    reviewRuns: (...a: unknown[]) => reviewRuns(...a),
    list: () => Promise.resolve({ ok: true, data: { findings: [] } }),
    reviewRunStandards: () => Promise.resolve({ ok: true, data: { standards: [] } }),
    reviewRunStandardsAll: () => Promise.resolve({ ok: true, data: { standards: [] } }),
    cancelJob: vi.fn(),
    startReviewRun: (...a: unknown[]) => startReviewRun(...a),
    previewCrs: vi.fn(), exportCrs: vi.fn(), decideCode: vi.fn(),
  },
}));

beforeEach(() => {
  documents.mockReset(); reviewRuns.mockReset(); startReviewRun.mockReset();
  documents.mockResolvedValue({
    ok: true,
    data: [{ id: "doc_sub", filename: "drum.pdf", document_role: "CONTRACTOR_SUBMITTAL" }],
  });
  reviewRuns.mockResolvedValue({ ok: true, data: { runs: [] } });
});

describe("the launcher a non-admin cannot use", () => {
  it("defaults to admin, matching every caller before #925", async () => {
    render(<ReviewRunsView />);
    await userEvent.selectOptions(await screen.findByLabelText("Submittal"), "doc_sub");
    expect(screen.getByRole("button", { name: /^Run AI review$/ }))
      .not.toBeDisabled();
  });

  it("disables the picker and the button, and says why, for a non-admin", async () => {
    render(<ReviewRunsView isAdmin={false} />);

    expect(await screen.findByLabelText("Submittal")).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Run AI review$/ })).toBeDisabled();
    expect(screen.getAllByText(/Only an administrator can start a review/).length)
      .toBeGreaterThan(0);
  });

  it("does not send a non-admin's empty state to the disabled launcher", async () => {
    render(<ReviewRunsView isAdmin={false} />);

    expect(await screen.findByText("No reviews have been run yet")).toBeInTheDocument();
    expect(screen.getByText(/Ask one to run a review/)).toBeInTheDocument();
    expect(screen.queryByText(/choose a contractor submittal above and select/))
      .not.toBeInTheDocument();
  });

  it("keeps the admin's original instruction unchanged", async () => {
    render(<ReviewRunsView isAdmin />);

    expect(await screen.findByText("No reviews have been run yet")).toBeInTheDocument();
    expect(screen.getByText(/choose a contractor submittal above and select/))
      .toBeInTheDocument();
  });
});
