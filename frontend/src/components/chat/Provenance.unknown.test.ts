/**
 * Only text from the PDF's own text layer may be called verbatim (audit
 * 2026-09-30). Every value that was not 'recognised' - a missing one, or a
 * "mixed" page - used to fall back to "Verbatim from PDF" / "quoted directly".
 */
import { describe, expect, it } from "vitest";

import type { AnswerPassage } from "../../types/api";
import { PROVENANCE_UNKNOWN, VERBATIM_STRINGS, provenanceDetail, provenanceLabel } from "./Provenance";

function passage(text_source: unknown): AnswerPassage {
  return {
    chunk_id: "c", document_id: "d", filename: "spec.pdf", page_start: 1, page_end: 1,
    section: null, text: "x", highlight: null, match_span: null, chunks_joined: 1,
    kind: "prose", score: 1, identifier_hits: [],
    text_source, ocr_min_conf: null, ocr_alphabet_violations: 0, ocr_alphabet_sample: null,
  } as AnswerPassage;
}

describe("provenance of a passage whose source is not recorded", () => {
  it.each([null, undefined, "mixed", "something-new"])(
    "never calls %s text verbatim", (source) => {
      const p = passage(source);
      expect(provenanceLabel(p)).toBe(PROVENANCE_UNKNOWN);
      expect(provenanceLabel(p)).not.toMatch(/verbatim/i);
      const detail = provenanceDetail(p);
      for (const claim of VERBATIM_STRINGS) expect(detail).not.toContain(claim);
      expect(detail).toMatch(/not recorded/);
    });

  it("still calls text-layer text verbatim", () => {
    expect(provenanceLabel(passage("extracted"))).toBe("Verbatim from PDF");
    expect(provenanceDetail(passage("extracted"))).toBe("quoted directly, no AI rewriting");
  });
});
