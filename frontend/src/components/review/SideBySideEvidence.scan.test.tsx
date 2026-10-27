/**
 * #505: a citation to a scanned page shows how well the page was read, with
 * what it is out of; a page with a text layer shows nothing. Invented data.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentRecord, ReviewFinding } from "../../types/api";
import { SideBySideEvidence } from "./SideBySideEvidence";

const findingEvidence = vi.fn();

vi.mock("../../api/client", () => ({
  reviews: { findingEvidence: (...args: unknown[]) => findingEvidence(...args) },
}));
vi.mock("./EvidencePageImage", () => ({
  EvidencePageImage: () => <div data-testid="preview" />,
}));

const SUB = { id: "doc-sub", filename: "scan.pdf" } as DocumentRecord;
const STD = { id: "doc-std", filename: "std.pdf" } as DocumentRecord;
const FINDING = {
  id: "f-1", contractor_page: 2, standard_page: 12, standard_clause: "6.1",
  contractor_evidence_text: "95 dB(A)", requirement_source_text: "Noise shall not exceed 90 dB(A).",
} as unknown as ReviewFinding;

function side(page: number, scan: unknown) {
  return { document_id: "d", filename: "x.pdf", page, box: "quote", reason: null, scan };
}

beforeEach(() => findingEvidence.mockReset());

async function open(submittalScan: unknown, standardScan: unknown = null) {
  findingEvidence.mockResolvedValue({
    ok: true,
    data: { finding_id: "f-1", submittal: side(2, submittalScan), standard: side(12, standardScan) },
  });
  render(<SideBySideEvidence finding={FINDING} submittal={SUB} standard={STD} onClose={vi.fn()} />);
  await waitFor(() => expect(screen.queryByText("Finding the cited page…")).toBeNull());
  return within(screen.getByRole("group", { name: "Submittal" }));
}

describe("scan quality beside the citation", () => {
  it("says how a scanned page was read, out of how many words", async () => {
    const sub = await open({
      tier: "poor", words: "scanned page, read poorly: check the words by eye",
      mean_conf: 0.55, low_conf_boxes: 20, box_count: 40,
    });
    expect(sub.getByText(/read poorly: check the words by eye \(20 of 40 words read with low confidence\)/))
      .toBeInTheDocument();
  });

  it("names a page that could not be read, with no count", async () => {
    const sub = await open({
      tier: "could_not_read", words: "scanned page: reading failed",
      mean_conf: null, low_conf_boxes: null, box_count: null,
    });
    expect(sub.getByText("scanned page: reading failed")).toBeInTheDocument();
  });

  it("shows nothing for a page with a text layer", async () => {
    await open(null);
    expect(screen.queryByText(/scanned page/)).toBeNull();
  });

  it("puts the line on the side it belongs to", async () => {
    await open(null, {
      tier: "clear", words: "scanned page, read clearly", mean_conf: 0.95, low_conf_boxes: 0, box_count: 30,
    });
    const std = within(screen.getByRole("group", { name: "Standard" }));
    expect(std.getByText(/read clearly \(0 of 30 words/)).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Submittal" })).queryByText(/scanned page/)).toBeNull();
  });
});
