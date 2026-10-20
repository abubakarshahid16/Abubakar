/**
 * The held-standards count on "How this was reviewed": the server's own
 * sentence under "Standards in scope", and nothing at all when no standard
 * was held. Made-up run.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ReviewRunSummary } from "../../../types/api";
import { StandardsSection } from "./StandardsSection";

const run = { review_run_id: "run-made-up", standards_in_scope: 1 } as unknown as ReviewRunSummary;
const sentence = "2 standards were held for the engineer because the equipment type is unsure; "
  + "their requirements were not checked. Counted among the standards in your library that this review considered.";

function show(heldEngineer: { count: number; sentence: string } | null | undefined) {
  cleanup();
  return render(<StandardsSection run={run} error={null}
    record={{ standards: [], missing: [], ...(heldEngineer === undefined ? {} : { heldEngineer }) }} />);
}

describe("StandardsSection held for the engineer", () => {
  afterEach(cleanup);
  it("prints the server's sentence as given", () => {
    show({ count: 2, sentence });
    expect(screen.getByTestId("standards-held-for-engineer").textContent).toBe(sentence);
  });
  it("renders nothing extra when none were held (null or absent)", () => {
    const base = show(undefined).container.textContent;
    expect(screen.queryByTestId("standards-held-for-engineer")).toBeNull();
    expect(show(null).container.textContent).toBe(base);
    expect(screen.queryByTestId("standards-held-for-engineer")).toBeNull();
    expect(base).not.toMatch(/held/i);
  });
});
