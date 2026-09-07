/**
 * Three defects observed in one live run, and the rules that now hold them.
 *
 *  1. "2 sentences were removed from this summary" over two bullets with no
 *     text in them. The disclosure is this app's honesty affordance; an empty
 *     one tells the reader something was hidden and then shows nothing. A
 *     bullet is rendered only for an entry that HAS the removed text, the
 *     count still counts every removal reported, and an entry whose text did
 *     not come back is named as that - never invented, never a bare bullet.
 *
 *  2. "Baseline  doc_4e2b3648e5fb". Every other surface names documents by
 *     filename. The baseline now does too, and an id that resolves to no
 *     filename is shown WITH the reason it is an id.
 *
 *  3. The same passage - same document, same page, same words - listed twice
 *     in one claim group. Identical rows collapse to one. Two different
 *     passages from the same page are two rows and stay two rows.
 *
 * Each test was mutation-proved: the guard it covers was removed, the test
 * went red, the guard was restored.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setToken } from "../api/client";
import { GapAnalysisCard } from "../components/analysis/GapAnalysisCard";
import type { EvidenceItem } from "../types/api";
import {
  AnalysisModeScreen,
  locate,
  resetAnalysisScreen,
  toClaimClusters,
} from "./AnalysisModeScreen";

// ------------------------------------------------------------------ fixtures

const EV: EvidenceItem = {
  evidence_id: "ev1",
  document_id: "doc_4e2b3648e5fb",
  filename: "doc13.pdf",
  page_start: 267,
  page_end: 267,
  section: null,
  exact_span:
    "Attachment D: LEED NC V2.2 Submittal Requirements presents a listing of required information and supporting documents for design and construction phase submittals.",
  text_source: "extracted",
  ocr_min_conf: null,
  ocr_alphabet_violations: 0,
  relevance_score: null,
  relevance_score_type: null,
};

function summaryBody(dropped: unknown[]) {
  return {
    question: "q",
    evidence_ledger: [EV],
    summary: "The submittal requirements are listed in Attachment D [S1].",
    summary_truncated: false,
    summary_cited_evidence_ids: ["ev1"],
    documented_findings: [],
    rejected_citations: [],
    evidence_removed: [],
    refusal: null,
    dropped_sentences: dropped,
    not_implemented_sections: [],
  };
}

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function mockSummary(body: unknown) {
  const fetch = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/analysis/summary")) return Promise.resolve(json(body));
    return Promise.reject(new Error(`unrouted ${url}`));
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

async function run() {
  fireEvent.change(screen.getByLabelText("Question"), { target: { value: "submittals" } });
  fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
  await screen.findByText(/removed from this summary/);
}

/** The disclosure itself. The screen has other lists on it; the rule under
 *  test is about the bullets INSIDE this <details>. */
function disclosure(): HTMLElement {
  const summary = screen.getByText(/removed from this summary/);
  const details = summary.closest("details");
  if (details === null) throw new Error("no <details> around the disclosure");
  return details;
}

beforeEach(() => {
  resetAnalysisScreen();
  setToken(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
  setToken(null);
  resetAnalysisScreen();
});

// --------------------------------- 1: the removed-sentence disclosure is real

describe("removed sentences: the disclosure is never empty", () => {
  it("renders NO bullet for an entry with no text, and still counts it", async () => {
    mockSummary(
      summaryBody([
        { sentence: "", reason: "" },
        { sentence: "   ", reason: "" },
      ]),
    );
    render(<AnalysisModeScreen />);
    await run();

    // The count tells the truth: two were removed.
    expect(screen.getByText(/2 sentences were removed from this summary/)).toBeInTheDocument();
    // And not one empty bullet is on screen.
    expect(within(disclosure()).queryAllByRole("listitem")).toHaveLength(0);
    expect(
      screen.getByText(/2 of them were reported without the removed text/),
    ).toBeInTheDocument();
  });

  it("renders the text, and the reason, when the payload carries them", async () => {
    mockSummary(
      summaryBody([
        {
          sentence: "The system is compliant with relevant standards.",
          reason: "carries a number no cited span contains: 250",
        },
      ]),
    );
    render(<AnalysisModeScreen />);
    await run();

    expect(screen.getByText(/1 sentence was removed from this summary/)).toBeInTheDocument();
    const items = within(disclosure()).getAllByRole("listitem");
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent("The system is compliant with relevant standards.");
    expect(items[0]).toHaveTextContent("carries a number no cited span contains: 250");
    // Nothing was withheld, so nothing says anything was.
    expect(screen.queryByText(/reported without the removed text/)).not.toBeInTheDocument();
  });

  it("still counts an entry that carries no `sentence` key at all", async () => {
    // A removal the API reported in a shape this screen cannot show is still a
    // removal. Dropping it from the count would understate what was hidden.
    mockSummary(summaryBody([{ reason: "cites no supplied source" }, {}]));
    render(<AnalysisModeScreen />);
    await run();

    expect(screen.getByText(/2 sentences were removed from this summary/)).toBeInTheDocument();
    expect(within(disclosure()).queryAllByRole("listitem")).toHaveLength(0);
    expect(
      screen.getByText(/2 of them were reported without the removed text/),
    ).toBeInTheDocument();
  });

  it("counts a text-bearing entry alongside a text-less one and shows only the former", async () => {
    mockSummary(
      summaryBody([
        { sentence: "", reason: "cites no supplied source" },
        { sentence: "It also mandates quarterly review.", reason: "fragment" },
      ]),
    );
    render(<AnalysisModeScreen />);
    await run();

    expect(screen.getByText(/2 sentences were removed from this summary/)).toBeInTheDocument();
    const items = within(disclosure()).getAllByRole("listitem");
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent("It also mandates quarterly review.");
    expect(
      screen.getByText(/One of them was reported without the removed text/),
    ).toBeInTheDocument();
  });
});

// ------------------------------------------ 2: the baseline is named, not idd

describe("gap baseline: named by filename", () => {
  const DOCS = [{ id: "doc_4e2b3648e5fb", filename: "doc13.pdf" }];

  function gaps(documentId: string | null) {
    return {
      applicability: "applicable" as const,
      baseline: {
        kind: "document" as const,
        document_id: documentId,
        section: null,
        text: null,
      },
      items: [],
    };
  }

  it("renders the filename, not the raw document id", () => {
    render(
      <GapAnalysisCard gaps={gaps("doc_4e2b3648e5fb")} documents={DOCS} onCite={() => {}} />,
    );
    expect(screen.getByText("doc13.pdf")).toBeInTheDocument();
    expect(screen.queryByText(/doc_4e2b3648e5fb/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Shown as an identifier/)).not.toBeInTheDocument();
  });

  it("shows an unresolvable id WITH the reason it is an id, never bare", () => {
    render(<GapAnalysisCard gaps={gaps("doc_not_in_ledger")} documents={DOCS} onCite={() => {}} />);
    expect(screen.getByText(/doc_not_in_ledger/)).toBeInTheDocument();
    expect(screen.getByText(/Shown as an identifier/)).toBeInTheDocument();
  });
});

// ------------------------------------------------- 3: identical rows show once

describe("claim rows: an identical row is one row", () => {
  const located = locate([EV, { ...EV, evidence_id: "ev2" }, { ...EV, evidence_id: "ev3" }]);

  function row(over: Record<string, unknown> = {}) {
    return {
      evidence_id: "ev1",
      filename: "doc13.pdf",
      page_start: 267,
      section: null,
      exact_span: EV.exact_span,
      raw_value: null,
      raw_unit: null,
      normalized_value: null,
      normalized_unit: null,
      ...over,
    };
  }

  it("collapses two identical rows - same document, same page, same words - to one", () => {
    const out = toClaimClusters(
      [{ facet: "submittals", label: "agreement", rows: [row(), row({ evidence_id: "ev2" })] }],
      located,
    );
    expect(out).toHaveLength(1);
    expect(out[0].rows).toHaveLength(1);
  });

  // SUPERSEDED. This test used to assert that two rows differing only in page
  // stayed two rows. That was wrong for the case that turned up next: a
  // sentence or a running heading across a page break gives byte-identical
  // text on p.267 and p.268, and showing it twice tells the reader nothing.
  // The page is no longer part of the key; see toClaimClusters, and
  // AnalysisModeScreen.emptyrow-dedup.test.tsx for the full rule.
  it("collapses two rows that differ ONLY in page, keeping the first", () => {
    const out = toClaimClusters(
      [
        {
          facet: "submittals",
          label: "agreement",
          rows: [row(), row({ evidence_id: "ev2", page_start: 268 })],
        },
      ],
      located,
    );
    expect(out[0].rows).toHaveLength(1);
    expect(out[0].rows[0].page_start).toBe(267);
  });

  it("keeps two rows that differ in text", () => {
    const out = toClaimClusters(
      [
        {
          facet: "submittals",
          label: "agreement",
          rows: [row(), row({ evidence_id: "ev2", exact_span: "A different passage on page 267." })],
        },
      ],
      located,
    );
    expect(out[0].rows).toHaveLength(2);
  });

  it("keeps two rows that differ in document", () => {
    const out = toClaimClusters(
      [
        {
          facet: "submittals",
          label: "agreement",
          rows: [row(), row({ evidence_id: "ev2", filename: "doc14.pdf" })],
        },
      ],
      located,
    );
    expect(out[0].rows).toHaveLength(2);
  });
});
