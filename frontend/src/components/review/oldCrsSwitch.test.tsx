/**
 * Owner order, 16 Nov 2026: "Old CRS download without the count line ... hide it behind a switch (off) so only the new one-CRS
 * file is offered. Do not delete code." The server says whether the older per-review files are offered (`old_crs_download` on
 * GET /api/reviews/page-v2). Off: the History box, the CRS page behind the sheet and the CRS & Reports list do not offer them, and
 * the sign-off's working copy is the paper's one CRS (team copy). On: everything as before. Made-up data only.
 */
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CrsSheetPage, OLD_CRS_FILE_OFF_LINE } from "./panels/BehindTheScenes";
import { OlderFiles } from "./v2/OlderFiles";
import type { CrsDecisions, CrsRow, ReviewNumbers } from "./workspace/contract";
import { WORKING_COPY_ONE_CRS_MESSAGE, useSignOff } from "./workspace/useSignOff";
import { RUN_CRS_OFF_LINE, ReviewCrsList } from "../../views/ReviewCrsList";

let offered = true;
const reviewRunsPage = vi.fn();
vi.mock("../../api/reviewPoints", async (orig) => ({
  ...(await orig<typeof import("../../api/reviewPoints")>()),
  oldCrsDownloadOffered: async () => offered,
}));
vi.mock("../../api/client", () => ({
  api: {},
  reviews: {
    previewCrs: async () => ({ ok: false, error: { code: "not_found", message: "x" } }),
    exportCrs: vi.fn(),
    reviewRunsPage: (...a: unknown[]) => reviewRunsPage(...a),
  },
}));
vi.mock("../../api/agentReview", () => ({ agentReview: { crsOlder: async () => ({ ok: false }) } }));
const downloadCrs = vi.fn();
vi.mock("./downloadCrs", () => ({ downloadCrs: (...a: unknown[]) => downloadCrs(...a) }));
const downloadPaperCrs = vi.fn();
vi.mock("./agent/downloadAgentCrs", () => ({
  downloadAgentCrs: vi.fn(), downloadPaperCrs: (...a: unknown[]) => downloadPaperCrs(...a),
}));
vi.mock("./crs/saveCrsDecisions", () => ({ saveCrsDecisions: vi.fn() }));

beforeEach(() => {
  reviewRunsPage.mockReset().mockResolvedValue({ ok: true, data: { total: 1, runs: [
    { review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "a.pdf", status: "completed", created_at: null },
  ] } });
  downloadCrs.mockReset().mockResolvedValue(null);
  downloadPaperCrs.mockReset().mockResolvedValue(null);
});

function signOff() {
  const decisions = { state: { decisions: {}, opened: {} }, unsaved: [], markSaved: vi.fn(), pendingRestore: null } as unknown as CrsDecisions;
  return renderHook(() => useSignOff({
    runId: "run-1", rows: [] as CrsRow[], decisions, refresh: async () => {},
    numbers: { unopenedNeedsYou: 0, signLeft: [] } as unknown as ReviewNumbers, documentId: "doc-1",
  }));
}

describe("the older per-review CRS files, switched off", () => {
  beforeEach(() => { offered = false; });

  it("History offers no older file", async () => {
    const { container } = render(<OlderFiles ruleCheckRun="r1" aiRun="r2" />);
    await waitFor(() => expect(container.innerHTML).toBe(""));
  });

  it("the CRS page behind the sheet does not offer the export and says where the file is", async () => {
    render(<CrsSheetPage runId="run-1" />);
    expect(await screen.findByTestId("crs-old-file-off")).toHaveTextContent(OLD_CRS_FILE_OFF_LINE);
    expect(screen.queryByRole("button", { name: /Export CRS - internal review copy/ })).toBeNull();
  });

  it("the CRS & Reports list does not offer the per-review file, and says where the file is", async () => {
    render(<ReviewCrsList />);
    await userEvent.click(screen.getByRole("button", { name: /Show the review runs' CRSs/ }));
    expect(await screen.findByTestId("crs-runs-off")).toHaveTextContent(RUN_CRS_OFF_LINE);
    expect(reviewRunsPage).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Download CRS/ })).toBeNull();
  });

  it("the working copy is the paper's one CRS, team copy, never the older file", async () => {
    const { result } = signOff();
    await act(async () => { await result.current.workingCopy(); });
    expect(downloadPaperCrs).toHaveBeenCalledWith("doc-1", "team");
    expect(downloadCrs).not.toHaveBeenCalled();
    expect(result.current.message).toBe(WORKING_COPY_ONE_CRS_MESSAGE);
  });
});

describe("the older per-review CRS files, switched on", () => {
  beforeEach(() => { offered = true; });

  it("History offers the rule check's and the AI review's older files", async () => {
    render(<OlderFiles ruleCheckRun="r1" aiRun="r2" />);
    await act(async () => {});
    expect(screen.getByRole("button", { name: "Rule check, internal copy" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI review, internal copy" })).toBeInTheDocument();
  });

  it("the CRS page behind the sheet offers the export", async () => {
    render(<CrsSheetPage runId="run-1" />);
    await act(async () => {});
    expect(screen.getByRole("button", { name: /Export CRS - internal review copy/ })).toBeInTheDocument();
    expect(screen.queryByTestId("crs-old-file-off")).toBeNull();
  });

  it("the CRS & Reports list offers the per-review file", async () => {
    render(<ReviewCrsList />);
    await userEvent.click(screen.getByRole("button", { name: /Show the review runs' CRSs/ }));
    expect(await screen.findByRole("button", { name: /Download CRS \(internal review copy\)/ })).toBeInTheDocument();
    expect(screen.queryByTestId("crs-runs-off")).toBeNull();
  });

  it("the working copy is the older file, as before", async () => {
    const { result } = signOff();
    await act(async () => { await result.current.workingCopy(); });
    expect(downloadCrs).toHaveBeenCalledWith("run-1", "internal");
    expect(downloadPaperCrs).not.toHaveBeenCalled();
    expect(result.current.message).toBe("Working copy downloaded. It is not signed.");
  });
});
