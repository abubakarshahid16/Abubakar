/**
 * #607: Quote mode runs only what its label says. Choosing Quote does not
 * switch Gap analysis on: the Gap analysis toggle stays off, the run plan
 * lists it as Off, and the result is a "Quoted evidence" section, not a
 * "Gap analysis" one. A truncated (work-budget) result says so.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EvidenceItem } from "../types/api";
import { AnalysisModeScreen, resetAnalysisScreen } from "./AnalysisModeScreen";
import { enginesFor } from "./analysis/analysisModel";

const EV: EvidenceItem = {
  evidence_id: "ev1", document_id: "doc_1", filename: "doc17.pdf", page_start: 12, page_end: 12,
  section: "4.2", exact_span: "The discharge pressure shall not be less than 250 kPa.",
  text_source: "extracted", ocr_min_conf: null, ocr_alphabet_violations: 0,
  relevance_score: null, relevance_score_type: null,
};

function gapsBody(over: Record<string, unknown> = {}) {
  return {
    question: "q", evidence_ledger: [EV],
    claim_clusters: [{
      facet: ["discharge pressure", "kPa"], label: "agreement",
      rows: [{ evidence_id: "ev1", filename: "doc17.pdf", page_start: 12, section: "4.2",
        exact_span: EV.exact_span, raw_value: "250", raw_unit: "kPa", normalized_value: null, normalized_unit: null }],
      note: null,
    }],
    gaps: { applicability: "not_applicable", baseline: null, items: [] },
    not_implemented_sections: [], ...over,
  };
}

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

function route(calls: string[], body: unknown = gapsBody()) {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    if (url.includes("/analysis/gaps")) return Promise.resolve(json(body));
    return Promise.reject(new Error(`unrouted ${url}`));
  }));
}

beforeEach(() => resetAnalysisScreen());
afterEach(() => vi.unstubAllGlobals());

describe("Quote mode does not switch Gap analysis on", () => {
  it("is its own engine: quote on, gap analysis off, whatever the toggles say", () => {
    const off = { gaps: false, market: false, recommendation: false };
    expect(enginesFor("quote", off)).toMatchObject({ quote: true, gaps: false, summary: false });
    expect(enginesFor("quote", { ...off, gaps: true }).gaps).toBe(false);
    expect(enginesFor("focused", { ...off, gaps: true })).toMatchObject({ quote: false, gaps: true });
    expect(enginesFor("focused", off).gaps).toBe(false);
  });

  it("leaves the Gap analysis checkbox unchecked after Quote is chosen", async () => {
    const user = userEvent.setup();
    render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("radio", { name: /Quote/ }));
    const box = screen.getByRole("checkbox", { name: /gap analysis/i }) as HTMLInputElement;
    expect(box.checked).toBe(false);
    const plan = screen.getByRole("region", { name: "Selected analysis work" });
    expect(within(plan).getByText("Quoted evidence")).toBeInTheDocument();
  });

  it("shows Quoted evidence after a Quote run and no Gap analysis section", async () => {
    const calls: string[] = [];
    route(calls);
    const user = userEvent.setup();
    render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("radio", { name: /Quote/ }));
    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(await screen.findByRole("region", { name: "Quoted evidence" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Gap analysis" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Gap analysis" })).toBeNull();
    expect(calls.filter((url) => url.includes("/analysis/summary"))).toHaveLength(0);
  });

  it("says a work-budget result is partial, and says why", async () => {
    const calls: string[] = [];
    route(calls, gapsBody({ truncated: true, truncation_reason: "time budget of 25 s reached" }));
    const user = userEvent.setup();
    render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("radio", { name: /Quote/ }));
    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(screen.getByRole("button", { name: "Run analysis" }));
    const section = await screen.findByRole("region", { name: "Quoted evidence" });
    expect(within(section).getByText(/Partial result: time budget of 25 s reached/)).toBeInTheDocument();
  });

  it("does not claim a partial result when the run finished", async () => {
    const calls: string[] = [];
    route(calls, gapsBody({ truncated: false, truncation_reason: null }));
    const user = userEvent.setup();
    render(<AnalysisModeScreen />);
    await user.click(screen.getByRole("radio", { name: /Quote/ }));
    await user.type(screen.getByLabelText("Question"), "what is the pressure floor");
    await user.click(screen.getByRole("button", { name: "Run analysis" }));
    const section = await screen.findByRole("region", { name: "Quoted evidence" });
    expect(within(section).queryByText(/Partial result/)).toBeNull();
  });
});
