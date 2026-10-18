/**
 * #967 PR1: the AI Submittal Review landing list - one row per document
 * from a contractor, one Review button.
 *
 * MUTATION PROOF: drop the orphan-run fallback in `rowsFor` and the second
 * test below fails (the run's document would vanish from the list); remove
 * the "Not reviewed" state and the first test fails; default the chip to
 * "all" and the Needs-me test fails; drop the earlier runs and the last
 * run test fails.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DocumentRecord, ReviewRunSummary } from "../../../types/api";
import { InboxList } from "./InboxList";

function doc(over: Partial<DocumentRecord> = {}): DocumentRecord {
  return {
    id: "doc-1", filename: "psv-sheet.pdf", document_role: "CONTRACTOR_SUBMITTAL",
    ...over,
  } as DocumentRecord;
}

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "psv-sheet.pdf",
    equipment_tags: [], status: "completed", created_at: "2026-10-01T00:00:00Z",
    standards_in_scope: 1, findings_total: 0, by_status: {},
    ...over,
  } as ReviewRunSummary;
}

describe("InboxList", () => {
  it("says a document has not been reviewed yet, with a Review button that starts one", async () => {
    const onReview = vi.fn();
    render(
      <InboxList
        documents={[doc()]} runs={[]} submittalsTotal={null}
        onReview={onReview} startingDocumentId={null}
      />,
    );
    expect(screen.getByText("psv-sheet.pdf")).toBeInTheDocument();
    expect(screen.getByText("Not reviewed")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Review" }));
    expect(onReview).toHaveBeenCalledWith("doc-1");
  });

  it("still lists a run whose document record is missing, under the run's own filename", () => {
    render(
      <InboxList
        documents={[]} runs={[run({ submittal_document_id: "doc-gone", submittal_filename: "orphan.pdf" })]}
        submittalsTotal={null} onReview={vi.fn()} startingDocumentId={null}
      />,
    );
    expect(screen.getByText("orphan.pdf")).toBeInTheDocument();
    expect(screen.getByText(/^Ready/)).toBeInTheDocument();
  });

  it("shows the latest run's plain status and date for a reviewed document", () => {
    render(
      <InboxList
        documents={[doc()]} runs={[run()]} submittalsTotal={null}
        onReview={vi.fn()} startingDocumentId={null}
      />,
    );
    expect(screen.getByText(/^Ready/)).toBeInTheDocument();
  });

  it("disables the button and says Starting… for the document being started", () => {
    render(
      <InboxList
        documents={[doc()]} runs={[]} submittalsTotal={null}
        onReview={vi.fn()} startingDocumentId="doc-1"
      />,
    );
    const button = screen.getByRole("button", { name: "Starting…" });
    expect(button).toBeDisabled();
  });

  it("starts on Needs me, counts each chip out of the documents listed, and filters by it", async () => {
    const docs = [doc({ id: "a", filename: "a.pdf" }), doc({ id: "b", filename: "b.pdf" }),
      doc({ id: "c", filename: "c.pdf" })];
    const runs = [
      run({ review_run_id: "r-a", submittal_document_id: "a" }),
      run({ review_run_id: "r-b", submittal_document_id: "b", crs_issued_at: "2026-10-02T00:00:00Z" }),
      run({ review_run_id: "r-c", submittal_document_id: "c", status: "running" }),
    ];
    render(
      <InboxList
        documents={docs} runs={runs} submittalsTotal={null}
        onReview={vi.fn()} startingDocumentId={null}
      />,
    );
    expect(screen.getByRole("button", { name: "Needs me (1 of 3)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("a.pdf")).toBeInTheDocument();
    expect(screen.queryByText("b.pdf")).not.toBeInTheDocument();
    expect(screen.queryByText("c.pdf")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Signed (1 of 3)" }));
    expect(screen.getByText("b.pdf")).toBeInTheDocument();
    expect(screen.queryByText("a.pdf")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Queued or running (1 of 3)" }));
    expect(screen.getByText("c.pdf")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "All (3 of 3)" }));
    expect(screen.getAllByTestId("inbox-state")).toHaveLength(3);
  });

  it("lists a document's earlier runs, each with its own state, and opens the one chosen", async () => {
    const onOpenRun = vi.fn();
    render(
      <InboxList
        documents={[doc()]}
        runs={[
          run({ review_run_id: "new", created_at: "2026-10-03T00:00:00Z" }),
          run({ review_run_id: "old", created_at: "2026-10-01T00:00:00Z", status: "failed", failure_reason: "stopped" }),
        ]}
        submittalsTotal={null} onReview={vi.fn()} onOpenRun={onOpenRun} startingDocumentId={null}
      />,
    );
    expect(screen.getByText("Earlier runs (1)")).toBeInTheDocument();
    expect(screen.getByText(/Failed: stopped/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^Open the run of/ }));
    expect(onOpenRun).toHaveBeenCalledWith("old");
  });

  it("says there are no documents yet when the list is empty", () => {
    render(
      <InboxList
        documents={[]} runs={[]} submittalsTotal={null}
        onReview={vi.fn()} startingDocumentId={null}
      />,
    );
    expect(screen.getByText("No documents from contractors yet")).toBeInTheDocument();
  });

  describe("#1114: a Ready row's comment counts", () => {
    it("shows the counts read from the run's own summary, asking once per run", async () => {
      const load = vi.fn().mockResolvedValue({ comment: 3, needs_you: 1 });
      const { rerender } = render(
        <InboxList
          documents={[doc()]} runs={[run()]} submittalsTotal={null}
          onReview={vi.fn()} startingDocumentId={null} loadReadyCounts={load}
        />,
      );
      expect(await screen.findByText(/^Ready: 3 comments, 1 needs you/)).toBeInTheDocument();
      rerender(
        <InboxList
          documents={[doc()]} runs={[run()]} submittalsTotal={null}
          onReview={vi.fn()} startingDocumentId={null} loadReadyCounts={load}
        />,
      );
      expect(load).toHaveBeenCalledTimes(1);
      expect(load).toHaveBeenCalledWith("run-1");
    });

    it("says Ready alone when the counts cannot be read", async () => {
      const load = vi.fn().mockResolvedValue(null);
      render(
        <InboxList
          documents={[doc()]} runs={[run()]} submittalsTotal={null}
          onReview={vi.fn()} startingDocumentId={null} loadReadyCounts={load}
        />,
      );
      await vi.waitFor(() => expect(load).toHaveBeenCalled());
      expect(screen.getByTestId("inbox-state").textContent).toMatch(/^Ready ·/);
    });

    it("does not ask for a run that is not Ready", () => {
      const load = vi.fn().mockResolvedValue({ comment: 1, needs_you: 0 });
      render(
        <InboxList
          documents={[doc()]} runs={[run({ status: "failed" })]} submittalsTotal={null}
          onReview={vi.fn()} startingDocumentId={null} loadReadyCounts={load}
        />,
      );
      expect(load).not.toHaveBeenCalled();
    });
  });
});
