/**
 * The dashboard picker asks for the backend maximum and states where the
 * list was cut. Invented identifiers only.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewDashboardPanel } from "./ReviewDashboardPanel";

const documents = vi.fn();
vi.mock("../../api/client", () => ({
  api: { documents: (...a: unknown[]) => documents(...a) },
  reviews: {
    dashboard: async () => ({ ok: true, data: {
      submittals_total: 450, submittals_awaiting_review: 1, standards_available: 3,
      standards_referenced_total: 0, standards_referenced_missing: 0,
      reviews_running: 0, reviews_awaiting_decision: 0, reviews_total: 0,
      needs_attention: 0, needs_attention_reasons: {}, recent: [],
    } }),
    startReviewRun: vi.fn(),
  },
}));

const rows = (n: number) => Array.from({ length: n }, (_, i) => ({ id: `d${i}`, filename: `SUB-A-${i}.pdf` }));

beforeEach(() => documents.mockReset());

describe("dashboard picker limit", () => {
  it("asks for 200 and says where the list was cut", async () => {
    documents.mockResolvedValue({ ok: true, data: rows(200), response: { headers: new Headers({ "X-Total-Count": "450" }) } });
    render(<ReviewDashboardPanel onOpenReview={vi.fn()} onOpenDocuments={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: /Upload Datasheet and Run AI Review/ }));
    expect(documents).toHaveBeenCalledWith(expect.objectContaining({ limit: 200 }));
    expect(await screen.findByTestId("submittals-boundary"))
      .toHaveTextContent("Showing the newest 200 of 450 contractor submittals");
  });

  it("says nothing when the whole list fits", async () => {
    documents.mockResolvedValue({ ok: true, data: rows(3), response: { headers: new Headers({ "X-Total-Count": "3" }) } });
    render(<ReviewDashboardPanel onOpenReview={vi.fn()} onOpenDocuments={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: /Upload Datasheet and Run AI Review/ }));
    await screen.findByRole("option", { name: "SUB-A-0.pdf" });
    expect(screen.queryByTestId("submittals-boundary")).toBeNull();
  });
});
