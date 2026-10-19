/**
 * Builder E: past reviews per document. Made-up sample data only.
 *
 * MUTATION PROOF (checked by hand once): drop the document filter in
 * `pastReviewsOf` and "keeps only that document's runs" fails; turn the
 * failed-count branch of `loadCommentCount` into `return 0` and "a failed
 * count shows nothing" fails; count N with a request and "counts N without
 * a request" fails; show recommended_code bare and "says the result in
 * plain words" fails.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentRecord, ReviewRunSummary } from "../../../types/api";
import { DocumentsFromContractors } from "../DocumentsFromContractors";
import { groupRunsByDocument } from "../reviewFormat";
import { PastReviewsButton } from "./PastReviewsButton";
import { PastReviewsList } from "./PastReviewsList";
import { loadCommentCount, loadPastReviews, pastReviewsOf } from "./pastReviews";

const reviewRuns = vi.fn();
const reviewRunSummary = vi.fn();

vi.mock("../../../api/client", () => ({
  reviews: {
    reviewRuns: (...args: unknown[]) => reviewRuns(...args),
    reviewRunSummary: (...args: unknown[]) => reviewRunSummary(...args),
  },
}));

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "Pump datasheet rev B.pdf",
    equipment_tags: [], status: "completed", created_at: "2026-10-01T08:00:00Z",
    standards_in_scope: 1, findings_total: 0, by_status: {}, recommended_code: null,
    ...over,
  } as ReviewRunSummary;
}

function summary(comment: number, needsYou: number) {
  return { ok: true, data: { rows: [], counts: { comment, needs_you: needsYou }, how_reviewed: {} } };
}

const RUNS: ReviewRunSummary[] = [
  run({ review_run_id: "run-1", created_at: "2026-10-01T08:00:00Z", status: "completed", recommended_code: "Approved with Comments" }),
  run({ review_run_id: "run-3", created_at: "2026-10-05T08:00:00Z", status: "completed", recommended_code: "Approved", engineer_final_code: "Rejected / Revise and Resubmit", crs_issued_at: "2026-10-06T09:00:00Z" }),
  run({ review_run_id: "run-2", created_at: "2026-10-03T08:00:00Z", status: "failed" }),
  run({ review_run_id: "run-9", submittal_document_id: "doc-2", submittal_filename: "Valve list.pdf", created_at: "2026-10-09T08:00:00Z" }),
];

beforeEach(() => {
  reviewRuns.mockReset();
  reviewRunSummary.mockReset();
});

describe("pastReviewsOf", () => {
  it("keeps only that document's runs, newest first, in groupRunsByDocument order", () => {
    const reviews = pastReviewsOf("doc-1", RUNS);
    expect(reviews.map((r) => r.runId)).toEqual(["run-3", "run-2", "run-1"]);
    const group = groupRunsByDocument(RUNS).find((g) => g.documentId === "doc-1")!;
    expect(reviews.map((r) => r.runId)).toEqual([group.latest, ...group.earlier].map((r) => r.review_run_id));
    expect(pastReviewsOf("doc-none", RUNS)).toEqual([]);
  });

  it("says the result in plain words: engineer's code as is, else the AI's code as proposed, else the status", () => {
    const byId = Object.fromEntries(pastReviewsOf("doc-1", RUNS).map((r) => [r.runId, r]));
    expect(byId["run-3"].result).toBe("Rejected / Revise and Resubmit");
    // Only proposed by the AI: never shown like the engineer's own code.
    expect(byId["run-1"].result).toBe("Proposed: Approved with Comments");
    expect(byId["run-2"].result).toBe("Failed");
    expect(byId["run-2"].result).not.toBe("failed");
  });

  it("marks signed from crs_issued_at and leaves the comment count unknown", () => {
    const byId = Object.fromEntries(pastReviewsOf("doc-1", RUNS).map((r) => [r.runId, r]));
    expect(byId["run-3"].signed).toBe(true);
    expect(byId["run-1"].signed).toBe(false);
    expect(Object.values(byId).every((r) => r.commentCount === null)).toBe(true);
  });
});

describe("adapters", () => {
  it("loadPastReviews asks for that document's runs and maps them", async () => {
    reviewRuns.mockResolvedValue({ ok: true, data: { runs: RUNS } });
    const res = await loadPastReviews("doc-1");
    expect(reviewRuns).toHaveBeenCalledWith("doc-1");
    expect(res.ok && res.reviews.map((r) => r.runId)).toEqual(["run-3", "run-2", "run-1"]);
  });

  it("loadPastReviews passes the API's message through on failure", async () => {
    reviewRuns.mockResolvedValue({ ok: false, disconnected: true, error: { code: "x", message: "Cannot reach the backend." } });
    expect(await loadPastReviews("doc-1")).toEqual({ ok: false, message: "Cannot reach the backend." });
  });

  it("loadCommentCount adds comments and needs-you; a failure is null, never 0", async () => {
    reviewRunSummary.mockResolvedValueOnce(summary(4, 2));
    expect(await loadCommentCount("run-1")).toBe(6);
    reviewRunSummary.mockResolvedValueOnce({ ok: false, disconnected: false, error: { code: "not_found", message: "no" } });
    expect(await loadCommentCount("run-1")).toBeNull();
    reviewRunSummary.mockRejectedValueOnce(new Error("boom"));
    expect(await loadCommentCount("run-1")).toBeNull();
  });
});

describe("PastReviewsButton", () => {
  it("counts N from the runs already loaded, without any request", () => {
    render(<PastReviewsButton documentId="doc-1" runs={RUNS} onOpenRun={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Past reviews (3)" })).toHaveAttribute("aria-expanded", "false");
    expect(reviewRuns).not.toHaveBeenCalled();
    expect(reviewRunSummary).not.toHaveBeenCalled();
  });

  it("is hidden when the document has no reviews", () => {
    const { container } = render(<PastReviewsButton documentId="doc-none" runs={RUNS} onOpenRun={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("opens the list inline, reads counts only then, and a row click opens that run", async () => {
    reviewRunSummary.mockImplementation((id: string) =>
      Promise.resolve(id === "run-2" ? { ok: false, disconnected: false, error: { code: "not_found", message: "no" } } : summary(id === "run-3" ? 5 : 1, 0)));
    const onOpenRun = vi.fn();
    render(<PastReviewsButton documentId="doc-1" runs={RUNS} onOpenRun={onOpenRun} />);
    expect(screen.queryByRole("list", { name: "Past reviews" })).not.toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: "Past reviews (3)" });
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const list = screen.getByRole("list", { name: "Past reviews" });
    await waitFor(() => expect(within(list).getByText("5 comments")).toBeInTheDocument());
    expect(within(list).getByText("1 comment")).toBeInTheDocument();
    expect(reviewRunSummary).toHaveBeenCalledTimes(3);

    await userEvent.click(within(list).getByText("Rejected / Revise and Resubmit"));
    expect(onOpenRun).toHaveBeenCalledWith("run-3");

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("list", { name: "Past reviews" })).not.toBeInTheDocument();
  });
});

describe("PastReviewsList", () => {
  it("shows date, result, comments and signed yes/no; a failed count shows nothing, never 0", async () => {
    reviewRunSummary.mockResolvedValue({ ok: false, disconnected: false, error: { code: "not_found", message: "no" } });
    render(<PastReviewsList reviews={pastReviewsOf("doc-1", RUNS)} onOpenRun={vi.fn()} />);
    await waitFor(() => expect(reviewRunSummary).toHaveBeenCalledTimes(3));
    const rows = screen.getAllByRole("button");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText("Signed: yes")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Signed: no")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Failed")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Proposed: Approved with Comments")).toBeInTheDocument();
    for (const row of rows) {
      expect(row.querySelector('[data-field="comments"]')).toBeEmptyDOMElement();
      expect(row.querySelector('[data-field="date"]')?.textContent).not.toBe("");
    }
    expect(screen.queryByText(/0 comments/)).not.toBeInTheDocument();
  });
});

describe("DocumentsFromContractors with onOpenPastRun", () => {
  const docs = [
    { id: "doc-1", filename: "Pump datasheet rev B.pdf", document_role: "CONTRACTOR_SUBMITTAL" },
    { id: "doc-3", filename: "Motor sheet.pdf", document_role: "CONTRACTOR_SUBMITTAL" },
  ] as DocumentRecord[];

  it("shows Past reviews (N) per reviewed row only when the prop is given", async () => {
    const onOpenPastRun = vi.fn();
    reviewRunSummary.mockResolvedValue(summary(2, 1));
    render(
      <DocumentsFromContractors
        documents={docs} runs={RUNS} submittalsTotal={null}
        onReview={vi.fn()} startingDocumentId={null} onOpenPastRun={onOpenPastRun}
      />,
    );
    expect(screen.getByRole("button", { name: "Past reviews (3)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Past reviews (1)" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Past reviews/ })).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Past reviews (1)" }));
    await userEvent.click(within(screen.getByRole("list", { name: "Past reviews" })).getByRole("button"));
    expect(onOpenPastRun).toHaveBeenCalledWith("run-9");
  });

  it("without the prop renders no past-reviews button and makes no request", () => {
    render(
      <DocumentsFromContractors
        documents={docs} runs={RUNS} submittalsTotal={null}
        onReview={vi.fn()} startingDocumentId={null}
      />,
    );
    expect(screen.queryByRole("button", { name: /Past reviews/ })).not.toBeInTheDocument();
    expect(reviewRuns).not.toHaveBeenCalled();
    expect(reviewRunSummary).not.toHaveBeenCalled();
  });
});
