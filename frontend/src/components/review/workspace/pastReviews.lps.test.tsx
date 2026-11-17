/**
 * Order 14 LPS S2 (rule 8, every home): with the redesigned page on, the past reviews list says the paper's page numbers and its note
 * says so, never "what each review found ... findings". Invented ids and numbers.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ReviewRunSummary } from "../../../types/api";
import { PastReviewsList } from "./PastReviewsList";
import { PAST_COUNTS_NOTE, PAST_PAGE_COUNTS_NOTE, pastReviewsOf } from "./pastReviews";

const PAGE = { not_met: 0, questions: 7, met: 1, does_not_apply: 0, to_confirm: 0, points: 8, undecided: 8, runs: { rule_check: null, ai_review: "run-1" } };
vi.mock("../../../api/reviewPoints", () => ({
  pageV2SwitchState: async () => true,
  reviewPoints: { pageCounts: async () => ({ ok: true, data: { boundary: "b", found: { "run-1": PAGE } } }) },
}));
vi.mock("../../../api/client", () => ({ reviews: { reviewRunCounts: async () => ({ ok: true, data: { counts: {} } }) } }));

const run = (over: Partial<ReviewRunSummary>) => ({
  review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "Invented sheet.pdf", equipment_tags: [], status: "completed",
  created_at: "2026-10-01T08:00:00Z", standards_in_scope: 1, findings_total: 0, by_status: {}, recommended_code: null, ...over,
}) as ReviewRunSummary;

describe("LPS S2: the past reviews note follows the page's numbers", () => {
  it("says the page's line and the page note, not the findings note", async () => {
    render(<PastReviewsList reviews={pastReviewsOf("doc-1", [run({}), run({ review_run_id: "run-0", created_at: "2026-09-01T08:00:00Z" })])} onOpenRun={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId("past-counts-note")).toHaveTextContent(PAST_PAGE_COUNTS_NOTE));
    expect(screen.getByTestId("past-counts-note")).not.toHaveTextContent(PAST_COUNTS_NOTE);
    expect(screen.getByText("Found by the review: 0 not met, 7 questions for you (8 points on its review page, 8 not decided yet)")).toBeInTheDocument();
  });
});
