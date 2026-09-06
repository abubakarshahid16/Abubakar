/**
 * How the gap rows are PRESENTED. Nothing here asserts a meaning: the five
 * statuses, the backend's note, the hedge and the engineer-review sentence are
 * load-bearing honesty text and are pinned elsewhere. These tests pin the
 * order a reader meets the rows in, the tally line above them, the withheld
 * label on a row with no passage, that a status is carried by words and not by
 * colour, and that the collapsed not-applicable rows are still reachable.
 *
 * Two known backend defects are deliberately NOT compensated for here: the
 * status/note mismatch, and facet labels that are query-term intersections
 * ("documents", "documents (%)"). The facet strings below are the real ones
 * from a real run, printed as sent.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GapAnalysisCard } from "./GapAnalysisCard";
import type { GapAnalysis, GapItem, GapItemStatus } from "../../types/analysis";

const DOCS = [{ id: "doc_baseline", filename: "Contract-Conditions.pdf" }];

const SPAN =
  "1.6 AS-AWARDED MODELS When applicable (see next paragraph) As-awarded models shall " +
  "incorporate all amendments to the solicitation documents (Request for Proposal, " +
  "Invitation to Bid, etc.).";

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

function renderCard(items: GapItem[]) {
  return render(<GapAnalysisCard gaps={card(items)} documents={DOCS} onCite={vi.fn()} />);
}

/** The facet marker of every row, as printed, in the order the DOM carries them. */
function facetOrder(): string[] {
  return screen
    .getAllByRole("listitem")
    .map((li) => li.querySelector("[data-facet]")?.textContent ?? "");
}

const STATUS_TEXT: Record<GapItemStatus, string> = {
  conflict: "Conflict",
  possible_gap: "Possible gap",
  insufficient_evidence: "Insufficient evidence",
  met: "Met",
  not_applicable: "Not applicable",
};

describe("P1 - rows are ordered by how much attention they deserve", () => {
  it("orders conflict, possible_gap, insufficient_evidence, met, not_applicable", () => {
    // Supplied in exactly the wrong order, so passing cannot be an accident of
    // the payload's own ordering.
    const supplied: GapItemStatus[] = [
      "not_applicable",
      "met",
      "insufficient_evidence",
      "possible_gap",
      "conflict",
    ];
    renderCard(supplied.map((status) => item({ status, facet: status })));

    expect(facetOrder()).toEqual([
      "conflict",
      "possible_gap",
      "insufficient_evidence",
      "met",
      "not_applicable",
    ]);
  });

  it("puts evidence-bearing rows first within a single status", () => {
    renderCard([
      item({ status: "possible_gap", facet: "no-evidence-a", project_citation_ids: [] }),
      item({ status: "possible_gap", facet: "has-evidence", project_citation_ids: ["ev_a", "ev_b"] }),
      item({ status: "possible_gap", facet: "no-evidence-b", project_citation_ids: [] }),
    ]);

    expect(facetOrder()).toEqual(["has-evidence", "no-evidence-a", "no-evidence-b"]);
  });

  it("keeps the payload's order between rows it cannot otherwise separate", () => {
    renderCard([
      item({ status: "met", facet: "first", project_citation_ids: ["ev_1"] }),
      item({ status: "met", facet: "second", project_citation_ids: ["ev_2"] }),
      item({ status: "met", facet: "third", project_citation_ids: ["ev_3"] }),
    ]);

    expect(facetOrder()).toEqual(["first", "second", "third"]);
  });
});

describe("P2 - the tally line counts what is there and claims nothing more", () => {
  it("states the totals of the rows actually rendered", () => {
    renderCard([
      item({ status: "possible_gap", facet: "a" }),
      item({ status: "possible_gap", facet: "b" }),
      item({ status: "possible_gap", facet: "c" }),
      item({ status: "not_applicable", facet: "d" }),
      item({ status: "not_applicable", facet: "e" }),
    ]);

    expect(screen.getByText("5 facets compared · 3 possible gaps · 2 not applicable")).toBeInTheDocument();
  });

  it("singularises, and names a conflict and a met row by their own words", () => {
    renderCard([
      item({ status: "conflict", facet: "a" }),
      item({ status: "met", facet: "b", project_citation_ids: ["ev_1"] }),
      item({ status: "insufficient_evidence", facet: "c" }),
    ]);

    expect(
      screen.getByText("3 facets compared · 1 conflict · 1 with insufficient evidence · 1 met"),
    ).toBeInTheDocument();
  });

  it("says 'facet' for one row", () => {
    renderCard([item({ status: "possible_gap", facet: "a" })]);
    expect(screen.getByText("1 facet compared · 1 possible gap")).toBeInTheDocument();
  });

  it("does not print a status with no rows as a zero", () => {
    renderCard([item({ status: "possible_gap", facet: "a" })]);
    const line = screen.getByText(/facet compared/);
    expect(line.textContent).not.toMatch(/\b0\b/);
    expect(line.textContent).not.toMatch(/conflict|not applicable|insufficient|met/);
  });

  it("states no verdict, score or percentage anywhere on the card", () => {
    renderCard([
      item({ status: "met", facet: "a", project_citation_ids: ["ev_1"] }),
      item({ status: "met", facet: "b", project_citation_ids: ["ev_2"] }),
    ]);
    const card = screen.getByRole("region", { name: "Gap analysis" });
    const text = (card.textContent ?? "").toLowerCase();

    for (const verdict of [
      /\bcompliant\b/,
      /\bcompliance\b/,
      /\boverall\b/,
      /looks good/,
      /no issues/,
      /\bpass\b/,
      /\bpassed\b/,
      /\bfail(ed|s)?\b/,
      /\bscore\b/,
      /\bcomplete\b/,
      /%/,
      /\d+\s*\/\s*\d+/,
    ]) {
      expect(text).not.toMatch(verdict);
    }
  });
});

describe("P3 - a row with no baseline passage carries no label over nothing", () => {
  it("renders neither the label nor the disclosure control", () => {
    renderCard([item({ baseline_span: "", baseline_citation_id: "ev_baseline00000001" })]);

    expect(screen.queryByText("Baseline, quoted verbatim")).toBeNull();
    expect(screen.queryByRole("button", { name: "Show baseline passage" })).toBeNull();
  });

  it("treats a whitespace-only span as no span", () => {
    renderCard([item({ baseline_span: "   \n  " })]);
    expect(screen.queryByText("Baseline, quoted verbatim")).toBeNull();
    expect(screen.queryByRole("button", { name: "Show baseline passage" })).toBeNull();
  });

  it("still renders both when there is a passage", () => {
    renderCard([item()]);
    expect(screen.getByText("Baseline, quoted verbatim")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show baseline passage" })).toBeInTheDocument();
    expect(screen.getByText(SPAN)).toBeInTheDocument();
  });

  it("a row without a passage still carries its status, evidence and note", () => {
    const note = "Only one document speaks to this facet.";
    renderCard([item({ baseline_span: "", status: "not_applicable", note })]);
    const row = screen.getByRole("listitem");
    expect(within(row).getByText(/Not applicable$/)).toBeInTheDocument();
    expect(within(row).getByText(note)).toBeInTheDocument();
  });
});

describe("P4 - the status is carried by text, never by colour alone", () => {
  it("survives every class attribute being stripped", () => {
    const statuses: GapItemStatus[] = [
      "conflict",
      "possible_gap",
      "insufficient_evidence",
      "met",
      "not_applicable",
    ];
    const { container } = renderCard(
      statuses.map((status) =>
        item({ status, facet: status, project_citation_ids: status === "met" ? ["ev_1"] : [] }),
      ),
    );

    // Remove every scrap of styling. A reader on a monochrome screen, or one
    // who cannot distinguish the tints, must still be told each status.
    for (const el of Array.from(container.querySelectorAll("[class]"))) {
      el.removeAttribute("class");
    }
    const text = container.textContent ?? "";
    for (const status of statuses) {
      expect(text).toContain(STATUS_TEXT[status]);
    }
  });

  it("the status word and its icon sit in one element, so the icon is never the only mark", () => {
    renderCard([item({ status: "conflict" })]);
    const mark = screen.getByText(/Conflict$/);
    expect(mark.textContent).toContain("Conflict");
    // The icon is decoration and is hidden from assistive technology.
    expect(mark.querySelector("[aria-hidden='true']")).not.toBeNull();
  });
});

describe("the backend's note is rendered as sent", () => {
  it("renders byte-identical to the payload", () => {
    const note =
      "One row carries a measurement or identifier the others lack; nothing is contradicted.";
    renderCard([item({ status: "possible_gap", project_citation_ids: ["ev_a"], note })]);

    const el = screen.getByText(note);
    expect(el.textContent).toBe(note);
  });

  it("does not normalise punctuation, spacing or case", () => {
    const note = "  Only ONE document speaks to this facet -- 1.6 §4  (see next paragraph).  ";
    renderCard([item({ status: "not_applicable", note })]);

    const row = screen.getAllByRole("listitem")[0];
    const match = Array.from(row.querySelectorAll("p")).find((p) => p.textContent === note);
    expect(match).toBeDefined();
    expect(match?.textContent).toBe(note);
  });

  it("renders nothing at all when the note is null", () => {
    renderCard([item({ status: "not_applicable", note: null, baseline_span: "" })]);
    const row = screen.getAllByRole("listitem")[0];
    for (const p of Array.from(row.querySelectorAll("p"))) {
      expect(p.textContent?.trim()).not.toBe("");
    }
    expect(row.textContent).not.toMatch(/N\/A|—\s*$|null|undefined/);
  });
});

describe("P5 - not-applicable rows are collapsed, not hidden", () => {
  function renderWithNotApplicable() {
    return renderCard([
      item({ status: "possible_gap", facet: "documents" }),
      item({ status: "not_applicable", facet: "documents (%)" }),
      item({ status: "not_applicable", facet: "section 4" }),
    ]);
  }

  it("shows the count without the reader expanding anything", () => {
    const { container } = renderWithNotApplicable();
    const details = container.querySelector("details");
    expect(details).not.toBeNull();
    expect(details?.open).toBe(false);
    expect(within(details as HTMLElement).getByText("2 facets not applicable")).toBeInTheDocument();
  });

  it("says 'facet' for a single not-applicable row", () => {
    renderCard([
      item({ status: "possible_gap", facet: "documents" }),
      item({ status: "not_applicable", facet: "section 4" }),
    ]);
    expect(screen.getByText("1 facet not applicable")).toBeInTheDocument();
  });

  it("keeps the rows one click away, with their content intact", async () => {
    const user = userEvent.setup();
    const { container } = renderWithNotApplicable();
    const details = container.querySelector("details") as HTMLDetailsElement;

    await user.click(screen.getByText("2 facets not applicable"));

    expect(details.open).toBe(true);
    const rows = within(details).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(details).getByText(/documents \(%\)$/)).toBeInTheDocument();
    expect(within(details).getByText(/section 4$/)).toBeInTheDocument();
  });

  it("renders no disclosure when nothing is not applicable", () => {
    const { container } = renderCard([item({ status: "possible_gap", facet: "documents" })]);
    expect(container.querySelector("details")).toBeNull();
    expect(screen.queryByText(/not applicable/)).toBeNull();
  });
});
