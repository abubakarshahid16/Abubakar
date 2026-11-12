/**
 * U2: the bar says whose steps it lists, speaks for the AI review when it has
 * open points, marks ONE step Next and says why a step waits.
 * MUTATION PROOF: mark every enabled step Next and the one-Next test fails;
 * draw the AI headline without `aiReview` and the quiet test fails.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ReviewRunSummary } from "../../../types/api";
import { ActionBar } from "./ActionBar";
import type { ActionStep, ReviewNumbers, SignOff } from "./contract";

vi.mock("../../../api/client", () => ({ api: {}, reviews: {} }));
const RUN = { review_run_id: "run-1", submittal_document_id: "d", status: "completed" } as unknown as ReviewRunSummary;
const IDLE: SignOff = { busy: false, message: null, error: null, save: vi.fn(), sign: vi.fn(), workingCopy: vi.fn() };
const N = { comments: 0, needsYou: 0, undecided: 0, unsaved: 0, signed: false, signedAt: null, signLeft: [], finalCodeRecorded: false } as unknown as ReviewNumbers;
const STEPS: ActionStep[] = [
  { id: "standards", label: "Upload missing standards (0)", count: 0, done: true, enabled: false },
  { id: "pages", label: "Check unread pages (0)", count: 0, done: true, enabled: false },
  { id: "decide", label: "Decide comments (0)", count: 0, done: true, enabled: false },
  { id: "code", label: "Record the final code", count: null, done: false, enabled: true },
  { id: "preview", label: "Preview CRS", count: null, done: false, enabled: true },
  { id: "sign", label: "Sign and export", count: null, done: false, enabled: false, detail: "Record the final code first." },
];
const bar = (aiReview?: { headline: string; next: string } | null) =>
  render(<ActionBar run={RUN} numbers={N} steps={STEPS} onAction={vi.fn()} signOff={IDLE} aiReview={aiReview} />);

describe("ActionBar (U2)", () => {
  it("names whose steps these are", () => {
    bar();
    expect(screen.getByTestId("ws-steps-owner")).toHaveTextContent("Steps of the rule check");
  });
  it("with open AI points the headline is the AI review's, and 'No comments' is only the rule check's line", () => {
    bar({ headline: "AI review: 20 points are still open.", next: "Next: read the AI review's points, then download the internal CRS." });
    expect(screen.getByTestId("ws-ai-headline")).toHaveTextContent("AI review: 20 points are still open. Next: read the AI review's points");
    expect(screen.getByTestId("ws-verdict")).toHaveTextContent(/^Rule check: No comments/);
  });
  it("without AI points the bar speaks as before", () => {
    bar(null);
    expect(screen.queryByTestId("ws-ai-headline")).toBeNull();
    expect(screen.getByTestId("ws-verdict")).toHaveTextContent(/^No comments/);
  });
  it("marks exactly one step Next, and says why a waiting step waits", () => {
    bar();
    expect(screen.getAllByTestId("ws-step-next")).toHaveLength(1);
    expect(screen.getByRole("button", { name: /Record the final code/ }).closest("li")).toContainElement(screen.getByTestId("ws-step-next"));
    expect(screen.getByTestId("ws-step-why-sign")).toHaveTextContent("Record the final code first.");
    expect(screen.queryByTestId("ws-step-why-standards")).toBeNull();
  });
});
