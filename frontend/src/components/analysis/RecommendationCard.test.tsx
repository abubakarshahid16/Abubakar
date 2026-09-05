/**
 * RecommendationCard: advisory, never a documented requirement. Confidence is a
 * word from a closed set of two, with no number, bar or percent behind it.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecommendationCard } from "./RecommendationCard";
import type { Recommendation } from "../../types/analysis";

function makeRec(over: Partial<Recommendation> = {}): Recommendation {
  return {
    text: "Specify coating system no. 1 at 280 µm nominal DFT for the splash zone [S1].",
    citation_ids: ["ev_7f3a9c1e2b4d6081"],
    basis: "documents_only",
    confidence: "low",
    checks: [
      { label: "Fewer than two documents contributed evidence", fired: true },
      { label: "Evidence contains recognised (OCR) text", fired: false },
    ],
    requires_engineer_approval: true,
    ...over,
  };
}

describe("RecommendationCard: null", () => {
  it("renders exactly the one sentence and nothing else", () => {
    const rec: Recommendation | null = null;
    expect(rec).toBeNull();
    const { container } = render(<RecommendationCard recommendation={rec} onCite={vi.fn()} />);
    expect(container.textContent).toBe("No recommendation was generated.");
    expect(container.querySelectorAll("*")).toHaveLength(1);
  });
});

describe("RecommendationCard: mandated wording", () => {
  it("renders the engineer review sentence verbatim", () => {
    render(<RecommendationCard recommendation={makeRec()} onCite={vi.fn()} />);
    expect(
      screen.getByText("Review and approval by a qualified engineer is required."),
    ).toBeInTheDocument();
  });

  it("keeps the AI-advisory label inside <summary> so it survives collapse", () => {
    const { container } = render(<RecommendationCard recommendation={makeRec()} onCite={vi.fn()} />);
    const summary = container.querySelector("summary");
    expect(summary).not.toBeNull();
    expect(summary!.textContent).toMatch(/AI Advisory — not a documented requirement/);
  });
});

describe("RecommendationCard: confidence is a word", () => {
  it("renders 'low' with no digit and no % anywhere", () => {
    // checks: [] so the "n of m checks fired" line, the only legitimate digit,
    // is absent and a numeric confidence has nowhere to hide.
    const rec = makeRec({ confidence: "low", checks: [], citation_ids: [], text: "Use system no. one." });
    expect(rec.confidence).toBe("low");
    expect(rec.checks).toHaveLength(0);
    const { container } = render(<RecommendationCard recommendation={rec} onCite={vi.fn()} />);
    expect(screen.getByText("low")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\d/);
    expect(container.textContent).not.toMatch(/%/);
  });

  it("never renders 'high' as a confidence value", () => {
    const rec = makeRec({ confidence: "medium", checks: [] });
    expect(rec.confidence).toBe("medium");
    const { container } = render(<RecommendationCard recommendation={rec} onCite={vi.fn()} />);
    expect(screen.getByText("medium")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/high/i);
  });

  it("renders every check's label with fired or clear", () => {
    const rec = makeRec();
    expect(rec.checks.some((c) => c.fired)).toBe(true);
    expect(rec.checks.some((c) => !c.fired)).toBe(true);
    render(<RecommendationCard recommendation={rec} onCite={vi.fn()} />);
    for (const c of rec.checks) {
      const li = screen.getByText(c.label).closest("li")!;
      expect(li).toHaveTextContent(c.fired ? /fired/ : /clear/);
      expect(li).not.toHaveTextContent(c.fired ? /clear/ : /fired/);
    }
  });
});
