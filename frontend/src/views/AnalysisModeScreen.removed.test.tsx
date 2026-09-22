/**
 * B34: sentences the checks removed are SHOWN - greyed, with the reason - and
 * never part of the answer.
 *
 * Before: the summary's removals sat inside a collapsed <details>, and the
 * recommendation's were thrown away by the backend and never reached this
 * screen. A reader looking at a short or empty answer had no way to see that
 * "SAES-H-001 also requires three coats of 300 micrometers" was cut, or why.
 *
 * Each rule below was mutation-proved (scripts/mutation_check.py, phase 31).
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EvidenceItem } from "../types/api";
import { AnalysisModeScreen, resetAnalysisScreen } from "./AnalysisModeScreen";

const EV: EvidenceItem = {
  evidence_id: "ev1",
  document_id: "doc_1",
  filename: "SAES-H-001.pdf",
  page_start: 64,
  page_end: 64,
  section: "4.1",
  exact_span: "Total system: minimum 150 micrometers.",
  text_source: "extracted",
  ocr_min_conf: null,
  ocr_alphabet_violations: 0,
  relevance_score: null,
  relevance_score_type: null,
};

const REMOVED = {
  sentence: "SAES-H-001 also requires three coats of 300 micrometers [S1].",
  reason: "value 300 not in cited passage",
};

function summaryBody(over: Record<string, unknown> = {}) {
  return {
    question: "q",
    evidence_ledger: [EV],
    summary: "SAES-H-001 requires a minimum of 150 micrometers [S1].",
    summary_truncated: false,
    summary_cited_evidence_ids: ["ev1"],
    documented_findings: [],
    rejected_citations: [],
    evidence_removed: [],
    refusal: null,
    removed: [REMOVED],
    not_implemented_sections: [],
    ...over,
  };
}

function recommendationBody(over: Record<string, unknown> = {}) {
  return {
    question: "q",
    evidence_ledger: [EV],
    recommendation: null,
    recommendation_refusal: null,
    removed: [REMOVED],
    public_market_findings: [],
    not_implemented_sections: [],
    ...over,
  };
}

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function routes(table: Record<string, () => Promise<Response>>) {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    for (const [fragment, make] of Object.entries(table)) if (url.includes(fragment)) return make();
    return Promise.reject(new Error(`unrouted ${url}`));
  }));
}

afterEach(() => vi.unstubAllGlobals());
beforeEach(() => resetAnalysisScreen());

async function ask(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Question"), "what is the minimum coating thickness");
  await user.click(screen.getByRole("button", { name: "Run analysis" }));
}

describe("B34: removed sentences are shown, greyed, and outside the answer", () => {
  it("shows the summary's removed sentence and its reason WITHOUT any click", async () => {
    const user = userEvent.setup();
    routes({ "/analysis/summary": () => Promise.resolve(json(summaryBody())) });
    render(<AnalysisModeScreen />);
    await ask(user);

    const region = await screen.findByRole("region", { name: "Sentences removed from this summary" });
    // Visible as rendered - not inside a collapsed <details>.
    expect(region.closest("details")).toBeNull();
    const [item] = within(region).getAllByRole("listitem");
    expect(item).toHaveTextContent(REMOVED.sentence);
    expect(item).toHaveTextContent("value 300 not in cited passage");
    // Greyed: muted text, reduced opacity, marked as removed.
    expect(item).toHaveAttribute("data-removed", "true");
    expect(item.className).toMatch(/opacity-70/);
  });

  it("the removed value appears ONLY in the removed region, never in the answer", async () => {
    const user = userEvent.setup();
    routes({ "/analysis/summary": () => Promise.resolve(json(summaryBody())) });
    render(<AnalysisModeScreen />);
    await ask(user);

    const region = await screen.findByRole("region", { name: "Sentences removed from this summary" });
    // The answer is on screen...
    expect(screen.getByText(/requires a minimum of 150 micrometers/)).toBeInTheDocument();
    // ...and every place "300 micrometers" is written is inside the removed region.
    const mentions = screen.getAllByText(/300 micrometers/);
    expect(mentions.length).toBeGreaterThan(0);
    for (const el of mentions) expect(region.contains(el)).toBe(true);
  });

  it("shows what was removed from a recommendation, even when none survived", async () => {
    const user = userEvent.setup();
    routes({
      "/analysis/summary": () => Promise.resolve(json(summaryBody({ removed: [] }))),
      "/analysis/recommendations": () => Promise.resolve(json(recommendationBody())),
    });
    render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("checkbox", { name: /generate recommendation/i }));
    await ask(user);

    const region = await screen.findByRole("region", { name: "Sentences removed from this recommendation" });
    const [item] = within(region).getAllByRole("listitem");
    expect(item).toHaveTextContent("value 300 not in cited passage");
    expect(item).toHaveAttribute("data-removed", "true");
    // The removals keep the section alive: it is not reported as "nothing was
    // generated", because something was - and was removed, with reasons.
    expect(screen.queryByText("No recommendation was generated.")).toBeNull();
  });
});
