/**
 * Two defects, both of the same family: telling a reader something is there and
 * then showing them nothing, or showing them the same thing twice.
 *
 * 1. A gap row with nothing of its own to show must not render as a bullet -
 *    the collapsed "N facets not applicable" summary already carries the count,
 *    and a bullet that repeats it and adds no word is a count over nothing. The
 *    count itself stays the payload's number and the shortfall is said out
 *    loud, the same way the summary's dropped sentences are.
 * 2. Byte-identical text from the SAME document is one row even when the pages
 *    differ - a sentence or a running heading across a page break. Identical
 *    text from DIFFERENT documents stays two rows, because two documents saying
 *    the same thing is exactly what a comparison is for.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GapAnalysisCard } from "../components/analysis/GapAnalysisCard";
import { locate, toClaimClusters } from "./AnalysisModeScreen";
import type { EvidenceItem, GapAnalysis, GapItem } from "../types/analysis";

// --------------------------------------------------------------- gap rows

const DOCS = [{ id: "doc_baseline", filename: "Contract-Conditions.pdf" }];

function gaps(items: GapItem[]): GapAnalysis {
  return {
    applicability: "applicable",
    baseline: { kind: "document", document_id: "doc_baseline", section: null, text: null },
    items,
  };
}

/** A not-applicable row exactly as the emptiest real one arrives: a status and
 *  nothing else. No facet, no passage, no evidence, no note. */
function emptyNotApplicable(over: Partial<GapItem> = {}): GapItem {
  return {
    facet: "",
    status: "not_applicable",
    baseline_citation_id: null,
    baseline_span: "",
    project_citation_ids: [],
    note: null,
    ...over,
  };
}

function notApplicableSection(): HTMLElement {
  const details = document.querySelector("details");
  if (details === null) throw new Error("no collapsed not-applicable section was rendered");
  return details as HTMLElement;
}

describe("a gap row never renders as an empty bullet", () => {
  it("renders no bullet at all for a not-applicable row carrying nothing", () => {
    render(
      <GapAnalysisCard gaps={gaps([emptyNotApplicable()])} documents={DOCS} onCite={vi.fn()} />,
    );
    const section = notApplicableSection();
    expect(within(section).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("keeps the count honest: it counts what the payload reported, not what it could show", () => {
    render(
      <GapAnalysisCard gaps={gaps([emptyNotApplicable()])} documents={DOCS} onCite={vi.fn()} />,
    );
    expect(screen.getByText(/1 facet not applicable/)).toBeInTheDocument();
    expect(
      screen.getByText(
        "One of them was reported with no facet, no passage, no evidence and no note, so it is not shown here.",
      ),
    ).toBeInTheDocument();
  });

  it("says how many were withheld when more than one was", () => {
    render(
      <GapAnalysisCard
        gaps={gaps([emptyNotApplicable(), emptyNotApplicable(), emptyNotApplicable()])}
        documents={DOCS}
        onCite={vi.fn()}
      />,
    );
    expect(screen.getByText(/3 facets not applicable/)).toBeInTheDocument();
    expect(
      screen.getByText(
        "3 of them were reported with no facet, no passage, no evidence and no note, so they are not shown here.",
      ),
    ).toBeInTheDocument();
    expect(within(notApplicableSection()).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("substitutes nothing for the row it withholds", () => {
    render(
      <GapAnalysisCard gaps={gaps([emptyNotApplicable()])} documents={DOCS} onCite={vi.fn()} />,
    );
    const text = notApplicableSection().textContent ?? "";
    expect(text).not.toMatch(/N\/A|—\s*—|\bnone\b/i);
  });

  // The other half of the rule: withholding is for rows that carry nothing, and
  // a row that carries anything at all is still a bullet with that thing in it.
  it("still renders a not-applicable row that HAS content", () => {
    render(
      <GapAnalysisCard
        gaps={gaps([emptyNotApplicable({ facet: "documents (%)", note: "Out of scope." })])}
        documents={DOCS}
        onCite={vi.fn()}
      />,
    );
    const section = notApplicableSection();
    expect(within(section).getAllByRole("listitem")).toHaveLength(1);
    expect(within(section).getByText("documents (%)")).toBeInTheDocument();
    expect(within(section).getByText("Out of scope.")).toBeInTheDocument();
    expect(section.textContent).not.toContain("not shown here");
  });

  it("renders a row whose only content is its facet", () => {
    render(
      <GapAnalysisCard
        gaps={gaps([emptyNotApplicable({ facet: "section 4" })])}
        documents={DOCS}
        onCite={vi.fn()}
      />,
    );
    expect(within(notApplicableSection()).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText("section 4")).toBeInTheDocument();
  });

  it("withholds the facet LABEL rather than printing it over an empty string", () => {
    render(
      <GapAnalysisCard
        gaps={gaps([emptyNotApplicable({ note: "Out of scope." })])}
        documents={DOCS}
        onCite={vi.fn()}
      />,
    );
    const section = notApplicableSection();
    expect(within(section).getAllByRole("listitem")).toHaveLength(1);
    expect(section.textContent).not.toContain("Facet");
  });
});

// ------------------------------------------------------------- claim rows

const SPAN =
  "Attachment D: LEED NC V2.2 Submittal Requirements presents a listing of required " +
  "information and supporting documents for design and construction phase submittals.";

const EV: EvidenceItem = {
  evidence_id: "ev268",
  document_id: "doc13",
  filename: "doc13.pdf",
  page_start: 268,
  page_end: 268,
  section: null,
  exact_span: SPAN,
  text_source: "extracted",
  ocr_min_conf: null,
  ocr_alphabet_violations: 0,
  relevance_score: null,
  relevance_score_type: null,
};

const LEDGER: EvidenceItem[] = [
  EV,
  { ...EV, evidence_id: "ev267", page_start: 267, page_end: 267 },
  { ...EV, evidence_id: "ev14", document_id: "doc14", filename: "doc14.pdf" },
];

function claimRow(over: Record<string, unknown> = {}) {
  return {
    evidence_id: "ev268",
    filename: "doc13.pdf",
    page_start: 268,
    section: null,
    exact_span: SPAN,
    raw_value: null,
    raw_unit: null,
    normalized_value: null,
    normalized_unit: null,
    ...over,
  };
}

function cluster(rows: Record<string, unknown>[]) {
  return [{ facet: "submittals", label: "agreement", rows }];
}

describe("identical claim text is one row per document", () => {
  const located = locate(LEDGER);

  it("collapses byte-identical text from the same document on adjacent pages", () => {
    const out = toClaimClusters(
      cluster([claimRow(), claimRow({ evidence_id: "ev267", page_start: 267 })]),
      located,
    );
    expect(out[0].rows).toHaveLength(1);
  });

  it("keeps the FIRST occurrence and its page", () => {
    const out = toClaimClusters(
      cluster([
        claimRow({ page_start: 268 }),
        claimRow({ evidence_id: "ev267", page_start: 267 }),
      ]),
      located,
    );
    expect(out[0].rows).toHaveLength(1);
    expect(out[0].rows[0].page_start).toBe(268);
    expect(out[0].rows[0].evidence_id).toBe("ev268");
  });

  it("keeps identical text from DIFFERENT documents as two rows", () => {
    const out = toClaimClusters(
      cluster([claimRow(), claimRow({ evidence_id: "ev14", filename: "doc14.pdf" })]),
      located,
    );
    expect(out[0].rows).toHaveLength(2);
    expect(out[0].rows.map((r) => r.filename)).toEqual(["doc13.pdf", "doc14.pdf"]);
  });

  it("keeps identical text from different documents even on the SAME page number", () => {
    const out = toClaimClusters(
      cluster([
        claimRow({ page_start: 268 }),
        claimRow({ evidence_id: "ev14", filename: "doc14.pdf", page_start: 268 }),
      ]),
      located,
    );
    expect(out[0].rows).toHaveLength(2);
  });

  it("keeps two rows when the text differs by a single character", () => {
    const out = toClaimClusters(
      cluster([
        claimRow(),
        claimRow({ evidence_id: "ev267", page_start: 267, exact_span: `${SPAN.slice(0, -1)}:` }),
      ]),
      located,
    );
    expect(out[0].rows).toHaveLength(2);
  });

  it("does not normalise whitespace, case or punctuation into a match", () => {
    const out = toClaimClusters(
      cluster([
        claimRow(),
        claimRow({ evidence_id: "ev267", page_start: 267, exact_span: ` ${SPAN}` }),
      ]),
      located,
    );
    expect(out[0].rows).toHaveLength(2);
  });
});
