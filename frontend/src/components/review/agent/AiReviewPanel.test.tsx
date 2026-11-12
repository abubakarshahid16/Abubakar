/**
 * The top panel "AI review of this document" (U2). MUTATION PROOF: draw it
 * for a state other than ok and the first test fails; drop the empty
 * contractor sentence and the second fails.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentLine, AgentRunSummary } from "../../../types/api";
import { AiReviewPanel } from "./AiReviewPanel";
import { CONTRACTOR_EMPTY_LINE } from "./plainWords";

const download = vi.fn();
vi.mock("./downloadAgentCrs", () => ({ downloadAgentCrs: (...a: unknown[]) => download(...a) }));
beforeEach(() => download.mockReset().mockResolvedValue(null));

const SUMMARY = { paper_kind: "datasheet", counts_by_class: { "Query for the engineer": 2 }, missing_books: [], models: [] } as unknown as AgentRunSummary;
const line = (over: Partial<AgentLine>) => ({
  item_id: "S-EQ-01", verdict_class: "Query for the engineer", word: "Query", clause: "1", rule_book: "Book A", reason: "", rule_tier: null, ...over,
}) as AgentLine;

describe("AiReviewPanel", () => {
  it("is drawn only when the run has an AI review", () => {
    const { container, rerender } = render(<AiReviewPanel runId="r1" overview={{ state: "none" }} onSeeEvery={() => {}} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<AiReviewPanel runId="r1" overview={{ state: "off" }} onSeeEvery={() => {}} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<AiReviewPanel runId="r1" overview={{ state: "ok", summary: SUMMARY, lines: [line({})], openPoints: 1 }} onSeeEvery={() => {}} />);
    expect(screen.getByRole("heading", { name: "AI review of this document" })).toBeInTheDocument();
    expect(screen.getByText(/Nothing here is final until an engineer confirms it/)).toBeInTheDocument();
    expect(screen.getByTestId("ai-panel-counts")).toHaveTextContent("1 question for the engineer, 0 proven by code");
  });
  it("says why the contractor copy is empty only when no failure was proven", () => {
    const { rerender } = render(<AiReviewPanel runId="r1" overview={{ state: "ok", summary: SUMMARY, lines: [line({})], openPoints: 1 }} onSeeEvery={() => {}} />);
    expect(screen.getByTestId("ai-panel-contractor-empty")).toHaveTextContent(CONTRACTOR_EMPTY_LINE);
    rerender(<AiReviewPanel runId="r1" overview={{ state: "ok", summary: SUMMARY, lines: [line({ verdict_class: "Proven by code", word: "Fail" })], openPoints: 1 }} onSeeEvery={() => {}} />);
    expect(screen.queryByTestId("ai-panel-contractor-empty")).toBeNull();
    // lines not all read: nothing is claimed about the contractor copy
    rerender(<AiReviewPanel runId="r1" overview={{ state: "ok", summary: SUMMARY, lines: null, openPoints: null }} onSeeEvery={() => {}} />);
    expect(screen.queryByTestId("ai-panel-contractor-empty")).toBeNull();
  });
  it("has the two downloads, each with its one line, and See every point", async () => {
    const seen = vi.fn();
    render(<AiReviewPanel runId="r1" overview={{ state: "ok", summary: SUMMARY, lines: [line({})], openPoints: 1 }} onSeeEvery={seen} />);
    await userEvent.click(screen.getByRole("button", { name: "Download CRS, contractor copy" }));
    expect(download).toHaveBeenCalledWith("r1", "contractor");
    await userEvent.click(screen.getByRole("button", { name: "Download CRS, internal copy" }));
    expect(download).toHaveBeenLastCalledWith("r1", "internal");
    expect(screen.getByText(/For the contractor: only the failures the code proved/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "See every point" }));
    expect(seen).toHaveBeenCalled();
  });
});
