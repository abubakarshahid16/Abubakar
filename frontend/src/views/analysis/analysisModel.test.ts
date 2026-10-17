/**
 * #1055 (cloud-2's note on PR #1056): `toGapItems` is the gate every Analysis
 * Hub gap payload passes through (`analysisStore`); a status it does not know
 * is dropped before the screen sees it. The new `beyond_requirement` status
 * must survive it, or the card's own group never renders.
 */
import { describe, expect, it } from "vitest";

import type { EvidenceItem } from "../../types/analysis";
import { toGapItems } from "./analysisModel";

const row = (status: string, facet: string) => ({
  facet, status, baseline_citation_id: null, baseline_span: "", project_citation_ids: ["ev_1"], note: null,
});
// the one cited evidence item, resolved - a row citing nothing resolvable is dropped by design
const located = new Map<string, EvidenceItem>([["ev_1", { evidence_id: "ev_1" } as unknown as EvidenceItem]]);

describe("toGapItems", () => {
  it("keeps a beyond-requirement row like every known status, and drops an unknown one", () => {
    const kept = toGapItems(
      [row("met", "a"), row("beyond_requirement", "extra"), row("not_applicable", "n"), row("made_up", "x")],
      located,
    );
    expect(kept.map((it) => `${it.facet}:${it.status}`)).toEqual(["a:met", "extra:beyond_requirement", "n:not_applicable"]);
  });
});
