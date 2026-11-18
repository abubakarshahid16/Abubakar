/** Order 14 lane E: the review page lists contractor submittals; with the suggested-role switch on, contract documents too.
 *  Switch off: the list request is the one it always was (CONTRACTOR_SUBMITTAL only). */
import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const documents = vi.fn();
const reviewRuns = vi.fn();
let sw = { enabled: false, review_roles: ["CONTRACTOR_SUBMITTAL"] };
vi.mock("../api/client", () => ({
  api: { documents: (...args: unknown[]) => documents(...args) },
  reviews: {
    reviewRuns: (...args: unknown[]) => reviewRuns(...args),
    reviewRunSummary: vi.fn(),
    reviewRunCounts: vi.fn().mockResolvedValue({ ok: true, data: { boundary: "", counts: {} } }),
  },
}));
vi.mock("../api/reviewPlan", () => ({ reviewPlan: { plan: vi.fn(), start: vi.fn() } }));
vi.mock("../components/review/workspace/NewReviewDropZone", () => ({ NewReviewDropZone: () => <p data-testid="drop-zone" /> }));
vi.mock("../api/roleSuggestion", () => ({ roleSuggestionSwitch: () => Promise.resolve(sw) }));

import { SubmittalsLandingView } from "./SubmittalsLandingView";

beforeEach(() => {
  documents.mockReset().mockResolvedValue({ ok: true, data: [] });
  reviewRuns.mockReset().mockResolvedValue({ ok: true, data: { runs: [] } });
});

describe("the roles the review page lists", () => {
  it("switch off: exactly the request it always made", async () => {
    sw = { enabled: false, review_roles: ["CONTRACTOR_SUBMITTAL"] };
    render(<SubmittalsLandingView onOpenRun={vi.fn()} workspace isAdmin />);
    await waitFor(() => expect(documents).toHaveBeenCalled());
    expect(documents.mock.calls[0]).toEqual([{ document_role: ["CONTRACTOR_SUBMITTAL"], limit: expect.any(Number) }]);
  });
  it("switch on: contract documents too", async () => {
    sw = { enabled: true, review_roles: ["CONTRACTOR_SUBMITTAL", "CONTRACT_DOCUMENT"] };
    render(<SubmittalsLandingView onOpenRun={vi.fn()} workspace isAdmin />);
    await waitFor(() => expect(documents).toHaveBeenCalled());
    expect(documents.mock.calls[0][0].document_role).toEqual(["CONTRACTOR_SUBMITTAL", "CONTRACT_DOCUMENT"]);
  });
});

describe("G2: the general review lists every paper that is not a rule book", () => {
  it("asks for every paper except the excluded roles, not only the listed roles", async () => {
    sw = { enabled: true, review_roles: ["CONTRACTOR_SUBMITTAL", "CONTRACT_DOCUMENT"], exclude_roles: ["COMPANY_STANDARD", "CRS_TEMPLATE"] } as typeof sw;
    render(<SubmittalsLandingView onOpenRun={vi.fn()} workspace isAdmin />);
    await waitFor(() => expect(documents).toHaveBeenCalled());
    const asked = documents.mock.calls[0][0];
    expect(asked.exclude_role).toEqual(["COMPANY_STANDARD", "CRS_TEMPLATE"]);
    expect(asked.document_role).toBeUndefined();
  });
});
