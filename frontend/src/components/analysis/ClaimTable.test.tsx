/**
 * ClaimTable: verbatim spans in a blockquote, "possible" conflicts, and a null
 * normalised value that renders nothing.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ClaimTable } from "./ClaimTable";
import type { ClaimCluster, ClaimRow } from "../../types/analysis";

function makeRow(over: Partial<ClaimRow> = {}): ClaimRow {
  return {
    evidence_id: "ev_1111222233334444",
    filename: "NORSOK-M-501-Rev5.pdf",
    page_start: 17,
    section: "A.1",
    exact_span: "Coating system no. 1 shall have a nominal dry film thickness of 280 um.",
    raw_value: "280",
    raw_unit: "um",
    normalized_value: 280,
    normalized_unit: "µm",
    ...over,
  };
}

describe("ClaimTable: empty", () => {
  it("renders the no-comparable-claims line", () => {
    const clusters: ClaimCluster[] = [];
    expect(clusters).toHaveLength(0);
    render(<ClaimTable clusters={clusters} onCite={vi.fn()} />);
    expect(
      screen.getByText("No comparable claims were extracted from the retrieved passages."),
    ).toBeInTheDocument();
  });
});

describe("ClaimTable: possible conflict", () => {
  it("says 'possible' and explains that revision/approval status is unknown", () => {
    const cluster: ClaimCluster = {
      facet: "Nominal DFT",
      label: "possible_conflict",
      rows: [
        makeRow(),
        makeRow({
          evidence_id: "ev_5555666677778888",
          filename: "Project-Coating-Spec.pdf",
          page_start: 4,
          exact_span: "Minimum dry film thickness: 320 microns.",
          raw_value: "320",
          raw_unit: "microns",
          normalized_value: 320,
        }),
      ],
    };
    expect(cluster.label).toBe("possible_conflict");
    render(<ClaimTable clusters={[cluster]} onCite={vi.fn()} />);
    expect(screen.getByText("Possible conflict")).toBeInTheDocument();
    expect(
      screen.getByText(/cannot be determined: documents carry no revision or approval status/),
    ).toBeInTheDocument();
  });

  it("does not render the conflict caption for an agreement cluster", () => {
    render(
      <ClaimTable clusters={[{ facet: "Nominal DFT", label: "agreement", rows: [makeRow()] }]} onCite={vi.fn()} />,
    );
    expect(screen.queryByText(/revision or approval status/)).toBeNull();
  });
});

describe("ClaimTable: normalised value", () => {
  it("renders no 'normalised' label when normalized_value is null, and one when it is not", () => {
    const unknownUnit = makeRow({
      evidence_id: "ev_aaaabbbbccccdddd",
      filename: "Legacy-Spec.pdf",
      exact_span: "Apply to 11 mils.",
      raw_value: "11",
      raw_unit: "mils",
      normalized_value: null,
      normalized_unit: null,
    });
    const known = makeRow();
    expect(unknownUnit.normalized_value).toBeNull();
    expect(known.normalized_value).toBe(280);

    render(
      <ClaimTable
        clusters={[{ facet: "Nominal DFT", label: "unresolved", rows: [known, unknownUnit] }]}
        onCite={vi.fn()}
      />,
    );

    const unknownLi = screen.getByText("Apply to 11 mils.").closest("li")!;
    expect(within(unknownLi).queryByText("normalised")).toBeNull();
    expect(within(unknownLi).getByText("as written")).toBeInTheDocument();

    const knownLi = screen.getByText(known.exact_span).closest("li")!;
    expect(within(knownLi).getByText("normalised")).toBeInTheDocument();
    expect(within(knownLi).getByText("280 µm")).toBeInTheDocument();
  });
});

describe("ClaimTable: verbatim span", () => {
  it("renders exact_span inside a blockquote", () => {
    const r = makeRow();
    render(<ClaimTable clusters={[{ facet: "Nominal DFT", label: "addition", rows: [r] }]} onCite={vi.fn()} />);
    const span = screen.getByText(r.exact_span);
    expect(span.tagName).toBe("BLOCKQUOTE");
  });
});
