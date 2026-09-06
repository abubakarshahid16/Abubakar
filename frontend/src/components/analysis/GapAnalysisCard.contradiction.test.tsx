/**
 * A gap row must not state two things a reader has to reconcile.
 *
 * Observed on screen: a row headed "▲ Possible gap" carrying three project
 * evidence chips, and directly under them the component's own sentence
 * "Retrieval found nothing addressing this." The row disproves its own
 * caption. The same sentence is correct - and deliberately hedged - on a row
 * that cites nothing, so the fix is a gate, not a rewording.
 *
 * These tests pin the gate in both directions, pin the captions that are the
 * component's own words as consistent with the status they belong to, and pin
 * that the backend's note and the baseline passage are still rendered as sent.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GapAnalysisCard } from "./GapAnalysisCard";
import type { GapAnalysis, GapItem, GapItemStatus } from "../../types/analysis";

const DOCS = [{ id: "doc_baseline", filename: "Contract-Conditions.pdf" }];

const NOTHING_FOUND = "Retrieval found nothing addressing this. That is not proof the documents say nothing.";
const POSITIVE_EVIDENCE = "Positive matching evidence was found.";

/** The baseline text from the reported defect, verbatim. */
const SPAN =
  '1.6 AS-AWARDED MODELS ... shall incorporate all amendments to the solicitation ' +
  'documents (Request for Proposal, Invitation to Bid, etc.).';

function item(over: Partial<GapItem> = {}): GapItem {
  return {
    facet: "documents",
    status: "possible_gap",
    baseline_citation_id: "ev_baseline00000001",
    baseline_span: SPAN,
    project_citation_ids: [],
    note: null,
    ...over,
  };
}

function card(items: GapItem[]): GapAnalysis {
  return {
    applicability: "applicable",
    baseline: { kind: "document", document_id: "doc_baseline", section: null, text: null },
    items,
  };
}

function renderRow(over: Partial<GapItem> = {}) {
  render(<GapAnalysisCard gaps={card([item(over)])} documents={DOCS} onCite={vi.fn()} />);
  return screen.getByRole("listitem");
}

describe("a row that cites evidence does not claim retrieval found nothing", () => {
  it("suppresses the absence sentence when evidence chips are present", () => {
    const row = renderRow({
      status: "possible_gap",
      project_citation_ids: ["ev_a", "ev_b", "ev_c"],
      note: "One row carries a measurement or identifier the others lack; nothing is contradicted.",
    });
    // The row really does carry the three chips from the report.
    expect(within(row).getAllByRole("button", { name: /Show project evidence/ })).toHaveLength(3);
    expect(within(row).queryByText(/Retrieval found nothing addressing this/)).toBeNull();
    expect(screen.queryByText(NOTHING_FOUND)).toBeNull();
  });

  it("suppresses it for a single chip too - one is not nothing", () => {
    renderRow({ status: "possible_gap", project_citation_ids: ["ev_only"] });
    expect(screen.queryByText(/Retrieval found nothing addressing this/)).toBeNull();
  });

  it("still renders the backend's own note on that row, unaltered", () => {
    const note = "One row carries a measurement or identifier the others lack; nothing is contradicted.";
    renderRow({ status: "possible_gap", project_citation_ids: ["ev_a", "ev_b", "ev_c"], note });
    expect(screen.getByText(note)).toBeInTheDocument();
  });
});

describe("a row that cites nothing keeps the hedge", () => {
  it("renders the absence sentence, in full, when no evidence is cited", () => {
    const row = renderRow({ status: "possible_gap", project_citation_ids: [] });
    expect(within(row).getByText("none cited")).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: /Show project evidence/ })).toBeNull();
    expect(screen.getByText(NOTHING_FOUND)).toBeInTheDocument();
  });
});

describe("the component's own explanation agrees with the status word it sits under", () => {
  const WITH: string[] = ["ev_a", "ev_b"];

  it("possible_gap: the absence claim appears only with zero evidence", () => {
    render(
      <GapAnalysisCard
        gaps={card([
          item({ facet: "cited", status: "possible_gap", project_citation_ids: WITH }),
          item({ facet: "uncited", status: "possible_gap", project_citation_ids: [] }),
        ])}
        documents={DOCS}
        onCite={vi.fn()}
      />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(within(rows[0]).queryByText(NOTHING_FOUND)).toBeNull();
    expect(within(rows[1]).getByText(NOTHING_FOUND)).toBeInTheDocument();
  });

  it("met: the presence claim appears only where evidence is actually cited", () => {
    render(
      <GapAnalysisCard
        gaps={card([
          item({ facet: "cited", status: "met", project_citation_ids: WITH }),
          item({ facet: "uncited", status: "met", project_citation_ids: [] }),
        ])}
        documents={DOCS}
        onCite={vi.fn()}
      />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(within(rows[0]).getByText(POSITIVE_EVIDENCE)).toBeInTheDocument();
    expect(within(rows[1]).queryByText(POSITIVE_EVIDENCE)).toBeNull();
  });

  it.each<GapItemStatus>(["conflict", "insufficient_evidence", "not_applicable"])(
    "%s: the component adds no explanation of its own, with or without evidence",
    (status) => {
      render(
        <GapAnalysisCard
          gaps={card([
            item({ facet: "cited", status, project_citation_ids: WITH }),
            item({ facet: "uncited", status, project_citation_ids: [] }),
          ])}
          documents={DOCS}
          onCite={vi.fn()}
        />,
      );
      expect(screen.queryByText(NOTHING_FOUND)).toBeNull();
      expect(screen.queryByText(POSITIVE_EVIDENCE)).toBeNull();
    },
  );

  it("never prints an absence claim and a presence claim in the same row", () => {
    for (const status of ["met", "possible_gap", "conflict", "insufficient_evidence", "not_applicable"] as const) {
      for (const ids of [[], ["ev_a"]]) {
        const { unmount } = render(
          <GapAnalysisCard
            gaps={card([item({ status, project_citation_ids: ids })])}
            documents={DOCS}
            onCite={vi.fn()}
          />,
        );
        const both =
          screen.queryByText(NOTHING_FOUND) !== null && screen.queryByText(POSITIVE_EVIDENCE) !== null;
        expect(both, `${status} / ${ids.length} chips`).toBe(false);
        unmount();
      }
    }
  });
});

describe("the row still shows what it always showed", () => {
  it("renders the status word and the baseline passage verbatim, evidence or not", () => {
    for (const ids of [[], ["ev_a", "ev_b", "ev_c"]]) {
      const { unmount } = render(
        <GapAnalysisCard
          gaps={card([item({ status: "possible_gap", project_citation_ids: ids })])}
          documents={DOCS}
          onCite={vi.fn()}
        />,
      );
      expect(screen.getByText("Possible gap")).toBeInTheDocument();
      expect(screen.getByText("Baseline, quoted verbatim")).toBeInTheDocument();
      expect(screen.getByText(SPAN)).toBeInTheDocument();
      unmount();
    }
  });

  it("keeps the status word for every status", () => {
    const words: Record<GapItemStatus, string> = {
      met: "Met",
      possible_gap: "Possible gap",
      conflict: "Conflict",
      insufficient_evidence: "Insufficient evidence",
      not_applicable: "Not applicable",
    };
    for (const [status, word] of Object.entries(words) as [GapItemStatus, string][]) {
      const { unmount } = render(
        <GapAnalysisCard
          gaps={card([item({ status, project_citation_ids: ["ev_a"] })])}
          documents={DOCS}
          onCite={vi.fn()}
        />,
      );
      expect(screen.getByText(word)).toBeInTheDocument();
      expect(screen.getByText(SPAN)).toBeInTheDocument();
      unmount();
    }
  });
});
