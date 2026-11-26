/**
 * The face of a file names its engine (lead-4, 26 Nov 2026): the Reviews list row says "Claude" or the local model's rough-draft
 * label, from the server's own words, and opens the face run. Invented ids and names only.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DocumentRecord, ReviewRunSummary } from "../../../../types/api";
import { LandingDocumentRow } from "./LandingDocumentRow";
import { landingRowsOf } from "./landingRows";

const doc = { id: "d1", filename: "INV-PAPER-1.pdf", document_role: "CONTRACTOR_SUBMITTAL" } as unknown as DocumentRecord;
const run = (id: string, created: string, over: Partial<ReviewRunSummary>): ReviewRunSummary =>
  ({ review_run_id: id, submittal_document_id: "d1", status: "completed", created_at: created, method: "general", ...over }) as ReviewRunSummary;

describe("LandingDocumentRow: the engine of the face", () => {
  it("opens the Claude review, names its engine, and keeps the newer rough draft among the earlier ones", () => {
    const runs = [
      run("claude", "2026-11-18T10:00:00Z", { face: true, engine: "claude", engine_words: "Claude" }),
      run("local", "2026-11-26T08:00:00Z", { face: false, engine: "local", engine_words: "Local model: rough draft, not scored as reliable" }),
    ];
    const [row] = landingRowsOf([doc], runs);
    const onOpenRun = vi.fn();
    render(<LandingDocumentRow row={row} counts={null} allRuns={runs} mayStart onOpenRun={onOpenRun} onChanged={vi.fn()} />);
    expect(screen.getByTestId("row-engine")).toHaveTextContent("Claude");
    screen.getByRole("button", { name: "Open the latest review of INV-PAPER-1.pdf" }).click();
    expect(onOpenRun).toHaveBeenCalledWith("claude");
  });
});
