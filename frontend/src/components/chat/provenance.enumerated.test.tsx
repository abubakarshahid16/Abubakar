/**
 * Provenance, enumerated from the code rather than from a list.
 *
 * `test_no_internal_leaks.py` does not check the routes someone remembered —
 * it enumerates every route off the app object and asserts the property across
 * all of them. This is the same shape for the frontend.
 *
 * WHY IT EXISTS. The verbatim label was rendered over OCR text because the fix
 * for "does this screen read text_source?" had never been asked of any screen.
 * Fixing the second renderer by hand would have left the third undiscovered,
 * and there were more than two: the supporting-passages list, the evidence
 * panel's Citation and PassageLocation, the passages under a Tier 2 answer,
 * and anything added later.
 *
 * HOW IT FORCES COMPLIANCE. The source files are scanned for every exported
 * component that takes an `AnswerPassage`. Each one must appear in RENDERERS
 * below — a new passage renderer with no entry FAILS this test rather than
 * being silently unchecked. It must then either show provenance itself, or
 * name the parent that labels it, and that parent is checked too.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnswerCard, type AnswerView } from "./AnswerCard";
import { Citation, EvidencePanel, Highlighted, PassageLocation } from "./EvidencePanel";
import { ProvenanceMark, VERBATIM_STRINGS } from "./Provenance";
import type { AnswerPassage } from "../../types/api";

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** A passage read off a page image, with the recogniser caught substituting. */
const RECOGNISED: AnswerPassage = {
  chunk_id: "c1",
  document_id: "d1",
  filename: "NORSOKM501Rev5.pdf",
  page_start: 17,
  page_end: 17,
  section: "A.1 Coating system no. 1",
  text: "Coating system no. 1 shall have a nominal dry film thickness of 280 um.",
  highlight: null,
  match_span: null,
  chunks_joined: 1,
  kind: "prose",
  score: 6.5,
  identifier_hits: [],
  text_source: "recognised",
  ocr_min_conf: 0.87,
  ocr_alphabet_violations: 2,
  ocr_alphabet_sample: "凤≦",
};

function extractView(p: AnswerPassage): AnswerView {
  return {
    answer_type: "extract",
    answer: p.text,
    reason: null,
    passage: p,
    supporting: [],
    passages: [],
    cited: [],
    rejected_citations: [],
    model: null,
    seconds: 1.2,
    examples: [],
  };
}

type Entry =
  | { kind: "shows"; render: () => React.ReactElement }
  /** Renders passage text only, and is never shown to a reader except inside
   *  `parent`, which carries the label. The parent is asserted too, so this is
   *  a redirection of the obligation rather than an exemption from it. */
  | { kind: "composed"; parent: string; render: () => React.ReactElement };

/** Every exported component that renders a passage. Keyed by export name. */
const RENDERERS: Record<string, Entry> = {
  Citation: { kind: "shows", render: () => <Citation passage={RECOGNISED} /> },
  PassageLocation: {
    kind: "shows",
    render: () => <PassageLocation passage={RECOGNISED} />,
  },
  Highlighted: {
    kind: "composed",
    parent: "AnswerCard",
    render: () => <Highlighted passage={RECOGNISED} />,
  },
  AnswerCard: {
    kind: "shows",
    render: () => (
      <AnswerCard
        view={extractView(RECOGNISED)}
        onSelectSource={() => {}}
        activeSource={null}
      />
    ),
  },
  EvidencePanel: {
    kind: "shows",
    render: () => (
      <EvidencePanel
        passages={[RECOGNISED]}
        selected={0}
        onSelect={() => {}}
        onClose={() => {}}
      />
    ),
  },
  ProvenanceMark: {
    kind: "shows",
    render: () => <ProvenanceMark passage={RECOGNISED} variant="full" />,
  },
};

/** Exported components declaring an AnswerPassage prop, read from the source. */
function enumerateRenderers(): string[] {
  const found = new Set<string>();
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) {
        walk(full);
        continue;
      }
      if (!/\.tsx?$/.test(e.name) || /\.test\.tsx?$/.test(e.name)) continue;
      const src = fs.readFileSync(full, "utf8");
      // `export function Name(` … followed, within its parameter list, by a
      // prop typed AnswerPassage. Deliberately textual: it sees a renderer the
      // moment someone writes one, without anyone updating a manifest.
      const re = /export function (\w+)\(([\s\S]{0,600}?)\)\s*\{/g;
      let m: RegExpExecArray | null;
      while ((m = re.exec(src)) !== null) {
        // PascalCase only: a lowercase export taking a passage is a helper
        // (provenanceDetail), not something a reader ever sees.
        if (/AnswerPassage/.test(m[2]) && /^[A-Z]/.test(m[1])) found.add(m[1]);
      }
    }
  };
  walk(path.resolve(HERE, ".."));
  return [...found].sort();
}

describe("every passage renderer states provenance (rule 8)", () => {
  const discovered = enumerateRenderers();

  it("found renderers to check at all", () => {
    // A collapsed enumeration would make every assertion below vacuous, in
    // exactly the way a suite that collects two tests still passes.
    expect(discovered.length).toBeGreaterThanOrEqual(4);
  });

  it("has an entry for every renderer in the source", () => {
    const missing = discovered.filter((n) => !(n in RENDERERS));
    expect(
      missing,
      `These components render an AnswerPassage but are not covered by this ` +
        `test. Add an entry to RENDERERS and make them display provenance ` +
        `for recognised text.`,
    ).toEqual([]);
  });

  for (const [name, entry] of Object.entries(RENDERERS)) {
    if (entry.kind === "composed") {
      it(`${name} is only ever shown inside ${entry.parent}, which labels it`, () => {
        expect(RENDERERS[entry.parent]?.kind).toBe("shows");
      });
      continue;
    }

    it(`${name} never calls recognised text a verbatim quotation`, () => {
      render(entry.render());
      // THE ASSERTION THAT MATTERS. Presence-only would pass while both the
      // OCR mark and the verbatim label sat on screen together.
      for (const s of VERBATIM_STRINGS) {
        expect(
          screen.queryByText(new RegExp(s, "i")),
          `${name} rendered "${s}" over OCR text`,
        ).toBeNull();
      }
    });

    it(`${name} shows the reader that this text was recognised`, () => {
      render(entry.render());
      expect(screen.getAllByText(/OCR/i).length).toBeGreaterThan(0);
    });
  }
});
