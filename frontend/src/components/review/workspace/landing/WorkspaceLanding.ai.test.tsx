/**
 * U2, finding 7: the list says what to do first, and marks the newest review
 * of a file that has an AI review. MUTATION PROOF: draw the mark for every
 * file and the second test fails; drop the first line and the first fails.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentRecord, ReviewRunSummary } from "../../../../types/api";

const summary = vi.fn();
vi.mock("../../../../api/agentReview", () => ({
  agentReview: { summary: (...a: unknown[]) => summary(...a) },
  agentSwitch: async () => ({ state: "on", status: { enabled: true, claude_lane_open: true } }),
}));
vi.mock("../../../../api/client", () => ({
  api: {}, auth: { me: async () => ({ ok: true, data: { required: true, user: { id: "u", roles: ["admin"] } } }) }, classification: {},
  reviews: { reviewRuns: async () => ({ ok: true, data: { runs: [] } }), readiness: vi.fn(), reviewRunCounts: vi.fn() },
}));
vi.mock("../NewReviewDropZone", () => ({ NewReviewDropZone: () => <p /> }));
vi.mock("../reviewWatch", () => ({ watchRun: vi.fn() }));

import { WorkspaceLanding } from "./WorkspaceLanding";

const run = (id: string, doc: string, at: string) => ({
  review_run_id: id, submittal_document_id: doc, submittal_filename: `${doc}.pdf`, status: "completed", created_at: at, equipment_tags: [],
}) as unknown as ReviewRunSummary;
const doc = (id: string) => ({ id, filename: `${id}.pdf`, uploaded_at: "2026-09-01T08:00:00Z", document_role: "CONTRACTOR_SUBMITTAL" }) as DocumentRecord;

beforeEach(() => {
  localStorage.clear();
  summary.mockReset().mockImplementation(async (id: string) => (id === "run-new-a"
    ? { ok: true, data: { counts_by_class: { "Query for the engineer": 13, "AI opinion, engineer to confirm": 7, "Not applicable": 4 } } }
    : { ok: false, disconnected: false, error: { code: "not_found", message: "x" } }));
});

describe("WorkspaceLanding: AI mark and first line", () => {
  it("says what to do first and marks only the newest review that has an AI review", async () => {
    render(<WorkspaceLanding documents={[doc("a"), doc("b")]} onOpenRun={vi.fn()} onReload={vi.fn()} submittalsTotal={2}
      loadReadyCounts={async () => ({})} isAdmin
      runs={[run("run-old-a", "a", "2026-10-01T08:00:00Z"), run("run-new-a", "a", "2026-10-05T08:00:00Z"), run("run-b", "b", "2026-10-02T08:00:00Z")]} />);
    expect(screen.getByTestId("landing-first-line")).toHaveTextContent("Open the newest review of a file, or start a new one");
    await waitFor(() => expect(screen.getAllByTestId("ai-mark")).toHaveLength(1));
    // 13 + 7 lines; the 4 that do not apply are not counted
    expect(screen.getByTestId("ai-mark")).toHaveTextContent("AI review: 20 lines");
    expect(summary).not.toHaveBeenCalledWith("run-old-a");
  });
  it("hints when the newest review has none but an older one has", async () => {
    summary.mockImplementation(async (id: string) => (id === "run-old-c"
      ? { ok: true, data: { counts_by_class: { "Query for the engineer": 1 } } }
      : { ok: false, disconnected: false, error: { code: "not_found", message: "x" } }));
    render(<WorkspaceLanding documents={[doc("c")]} onOpenRun={vi.fn()} onReload={vi.fn()} submittalsTotal={1}
      loadReadyCounts={async () => ({})} isAdmin
      runs={[run("run-old-c", "c", "2026-10-01T08:00:00Z"), run("run-new-c", "c", "2026-10-05T08:00:00Z")]} />);
    await waitFor(() => expect(screen.getByTestId("ai-earlier-hint")).toHaveTextContent("An earlier review of this file has an AI review"));
    expect(screen.queryByTestId("ai-mark")).toBeNull();
  });
});
