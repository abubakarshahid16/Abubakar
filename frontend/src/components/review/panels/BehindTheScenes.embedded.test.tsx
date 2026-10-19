/**
 * v2.1 gaps W2 and T2: inside the workspace the behind-the-scenes pages
 * hide their own navigation and heading (one set of tabs), the old screens
 * keep them; the standards list says how each standard was chosen in plain
 * words, with the stored code folded under "Details". Made-up data.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ReviewRunStandard, ReviewRunSummary } from "../../../types/api";
import { BehindTheScenes, type BehindTheScenesProps } from "./BehindTheScenes";
import { SELECTION_METHOD_UNRECORDED, selectionMethodWords } from "./selectionMethodWords";

vi.mock("../../../api/client", () => ({
  api: {},
  reviews: {
    reviewRunStandardsAll: async () => ({ ok: true, data: { standards: [] } }),
    overrideRunStandard: vi.fn(),
  },
}));

const RUN = {
  review_run_id: "run-1", submittal_document_id: "doc-sub", submittal_filename: "Pump datasheet rev B.pdf",
  status: "completed", created_at: "2026-10-01T00:00:00Z", findings_total: 0, by_status: {},
} as unknown as ReviewRunSummary;

function std(id: string, method: string | null): ReviewRunStandard {
  return {
    standard_document_id: id, filename: `${id}.pdf`, selection_method: method, selection_reason: "made-up reason",
    confidence: null, included: true, exclusion_reason: null, evidence_page: null, evidence_quote: null, scope_decision: null,
  } as unknown as ReviewRunStandard;
}

function page(over: Partial<BehindTheScenesProps> = {}) {
  const props: BehindTheScenesProps = {
    panel: "standards", run: RUN, findings: [], documents: [],
    standardsState: { standards: [], missing: [], error: null }, focusStatus: null,
    onOpenPanel: vi.fn(), onFocusStatus: vi.fn(), onStandardsChanged: vi.fn(), onChanged: vi.fn(),
    ...over,
  };
  return render(<BehindTheScenes {...props} />);
}

describe("W2: one set of tabs inside the workspace", () => {
  it("the old screens keep the inner navigation and heading (default)", () => {
    page();
    expect(screen.getByRole("navigation", { name: "Behind the scenes" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /The rule books used · Pump datasheet rev B\.pdf/ })).toBeInTheDocument();
  });

  it("embedded: no inner navigation, no second title", () => {
    page({ embedded: true });
    expect(screen.queryByRole("navigation", { name: "Behind the scenes" })).toBeNull();
    expect(screen.queryByRole("button", { name: "← Back to the sheet" })).toBeNull();
    expect(screen.queryByText(/The rule books used/)).toBeNull();
    expect(screen.queryByText(/What each AI step did on this review/)).toBeNull();
  });
});

describe("T2: how each standard was chosen, in plain words", () => {
  it("shows plain words with the stored code only under Details", () => {
    page({ standardsState: {
      standards: [std("API-610", "referenced"), std("ISO-5199", "semantic"), std("NACE-1", "value_conflict"), std("ASME-8", null)],
      missing: [], error: null,
    } });
    const chips = screen.getAllByTestId("standard-chosen-by");
    expect(chips[0]).toHaveTextContent("Named in the document");
    expect(chips[1]).toHaveTextContent("Found by similar wording (a guess, not named in the document)");
    expect(chips[2]).toHaveTextContent("Value conflict");
    expect(chips[3]).toHaveTextContent(SELECTION_METHOD_UNRECORDED);
    // The raw code sits inside a closed <details>, not as the chip's words.
    const fold = chips[0].querySelector("details");
    expect(fold).not.toBeNull();
    expect(fold?.open).toBe(false);
    expect(within(fold as HTMLElement).getByText("referenced")).toBeInTheDocument();
    expect(chips[0].querySelector(".rounded-full")?.textContent).toBe("Named in the document");
    expect(chips[3].querySelector("details")).toBeNull();
    expect(screen.queryByText("unrecorded")).toBeNull();
  });

  it("every code the server writes has words, and none is empty", () => {
    for (const code of ["referenced", "possible_citation", "equipment_type", "governing_standard", "discipline",
      "service", "semantic", "project", "manual", "model", "scope"]) {
      const entry = selectionMethodWords(code);
      expect(entry.words, code).not.toMatch(/_/);
      expect(entry.words.length, code).toBeGreaterThan(0);
      expect(entry.detail).toBe(code);
    }
  });
});
