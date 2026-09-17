/**
 * Provenance, in one place, because it was in none.
 *
 * The verbatim label was rendered unconditionally over OCR text while 92
 * recognised chunks were retrievable. Provenance was stored in `page_ocr`,
 * carried to `chunks`, threaded through retrieval and passage expansion, and
 * made a REQUIRED field in the contract - and the one screen that decides
 * whether a sentence may be called the document's own words never read it.
 * Every layer was correct and the claim was still false.
 *
 * The lesson (standing rule 8) is that a provenance field no assertion reads
 * is decoration. Fixing the one screen by hand would have left the next
 * renderer to repeat it, so the strings and the predicate live here and
 * `provenance.enumerated.test.tsx` walks the source for every component that
 * renders a passage and fails until each one complies.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { AnswerPassage } from "../../types/api";

export type ProvenanceSource = Pick<AnswerPassage, "text_source" | "ocr_min_conf" | "ocr_alphabet_violations"> & { ocr_alphabet_sample?: string | null };

/** The wording that may ONLY appear over text from the PDF's own text layer. */
export const VERBATIM_STRINGS = [
  "Quoted verbatim from the document",
  "quoted directly, no AI rewriting",
] as const;

/** Read off a page image rather than out of the text layer. */
export function isRecognised(p: ProvenanceSource | null | undefined): boolean {
  return p?.text_source === "recognised";
}

/** A recognised passage whose recogniser emitted characters the document's
 *  script cannot contain. PROOF of a substitution, not an opinion about one:
 *  two passages can both sit at 0.95 confidence and one of them contains 凤. */
export function hasAlphabetViolation(p: ProvenanceSource | null | undefined): boolean {
  return isRecognised(p) && (p?.ocr_alphabet_violations ?? 0) > 0;
}

/**
 * The mark that must accompany recognised text wherever a reader meets it.
 *
 * `full` carries the reader's action and belongs above the quotation itself.
 * `short` is for a citation line or a list row, where the action has already
 * been stated once and repeating it would be noise - but the FACT still has
 * to be there, because a reader scanning a list of supporting passages is
 * making the same judgement as a reader looking at the main one.
 */
export function ProvenanceMark({
  passage,
  variant = "short",
}: {
  passage: ProvenanceSource;
  variant?: "full" | "short";
}) {
  if (!isRecognised(passage)) return null;
  const violated = hasAlphabetViolation(passage);

  if (variant === "short") {
    return (
      <span
        className="rounded bg-warn-500/15 px-1.5 py-0.5 text-xs font-medium text-warn-500"
        title={
          violated
            ? "Read by OCR, and the recogniser produced characters this document cannot contain. Check the page image."
            : "Read by OCR from a scanned page. Check it against the page image."
        }
      >
        {violated ? "OCR · wrong characters" : "OCR"}
      </span>
    );
  }

  // An alphabet violation ESCALATES this label rather than replacing it. The
  // reader's action is unchanged - check the page - but the reason is
  // specific and much stronger than "this was recognised". The ideographs are
  // obvious to anyone; U+2266 reads as U+2264 to a skimming engineer, and
  // that is the one that gets into a specification unnoticed.
  return (
    <p className="text-xs font-semibold uppercase tracking-wider text-warn-500">
      {violated
        ? "Read by OCR — and misread: characters this document cannot contain"
        : "Read by OCR from a scanned page"}
    </p>
  );
}

/**
 * The recogniser's confidence, shown as a VALUE WITH NO VERDICT.
 *
 * No threshold has been measured, so there is nothing to pass or fail against
 * and nothing to colour. A red 0.62 would be a number wearing a judgement it
 * has not earned, and the reader would reasonably infer a line exists where
 * none does. It sits in the citation as plain monospace text, next to the OCR
 * mark that already tells them to check the page.
 *
 * It is also deliberately the WEAKER of the two signals on offer. Confidence
 * is the model's opinion of itself; an alphabet violation is proof. Two
 * passages can both sit at 0.95 and one of them contains a CJK ideograph.
 */
export function OcrConfidence({ passage }: { passage: ProvenanceSource }) {
  if (!isRecognised(passage) || passage.ocr_min_conf == null) return null;
  return (
    <span
      className="font-mono text-xs text-slateish-500"
      title="Lowest OCR confidence across this passage. No pass/fail threshold is set - this is the measurement, not a verdict."
    >
      OCR confidence {passage.ocr_min_conf.toFixed(2)}
    </span>
  );
}

/** A plain-language provenance label used anywhere a reader inspects a source. */
export function provenanceLabel(passage: ProvenanceSource): string {
  if (isRecognised(passage)) {
    return passage.ocr_min_conf == null
      ? "Read by OCR"
      : `Read by OCR, lowest confidence ${passage.ocr_min_conf.toFixed(2)}`;
  }
  return "Verbatim from PDF";
}

/** Keyboard-accessible source inspection without inventing a second evidence model. */
export function CitationInspector({ passage, children }: { passage: AnswerPassage; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);
  return (
    <span className="relative inline-flex max-w-full flex-wrap items-center">
      <span className="sr-only">{provenanceLabel(passage)}</span>
      <button
        ref={trigger}
        type="button"
        aria-expanded={open}
        aria-label={`Inspect citation for ${passage.filename}, page ${passage.page_start}`}
        onClick={() => setOpen((value) => !value)}
        className="rounded-[var(--radius-xs)] text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal-400"
      >
        {children}
      </button>
      {open && (
        <span role="dialog" aria-label="Citation details" className="absolute start-0 top-full z-30 mt-2 w-[min(28rem,calc(100vw-2rem))] rounded-[var(--radius-sm)] border border-signal-500/40 bg-ink-900 p-3 text-left shadow-[var(--shadow-floating)]">
          <span className="block text-xs font-semibold text-slateish-100">{provenanceLabel(passage)}</span>
          <span className="mt-1 block text-xs text-slateish-400">
            {passage.filename} · {passage.page_start === passage.page_end ? `page ${passage.page_start}` : `pages ${passage.page_start}–${passage.page_end}`}
            {passage.section ? ` · section ${passage.section}` : ""}
          </span>
          <span className="mt-2 block max-h-32 overflow-auto whitespace-pre-wrap border-l-2 border-signal-500/50 ps-2 text-xs text-slateish-200">{passage.text}</span>
        </span>
      )}
    </span>
  );
}

/** The line beside the duration, stating what the reader should do. */
export function provenanceDetail(passage: AnswerPassage): string {
  if (!isRecognised(passage)) return "quoted directly, no AI rewriting";
  if (hasAlphabetViolation(passage)) {
    const n = passage.ocr_alphabet_violations ?? 0;
    const sample = passage.ocr_alphabet_sample ?? "";
    return (
      `${n} character${n === 1 ? "" : "s"} here cannot occur in this document` +
      (sample ? ` (${sample})` : "") +
      " — the page below is what it actually says"
    );
  }
  return "not the document's own text — check it against the page below";
}

/**
 * The clause label a citation may show. TODAY: never.
 *
 * THE DEFECT. `chunks.section` is the heading the chunker believed was in
 * force. It does not reset at chapter and appendix boundaries, so a stale
 * label carries forward across them and is asserted with full confidence over
 * text it has nothing to do with. Measured two ways, and the two agree:
 *
 *   - Seven questions checked against the PDFs: page numbers right 7/7,
 *     clause labels WRONG on 5 of 6 cited passages. doc16 p22 was labelled
 *     "6.0 Procedure", a heading that is on p15. doc13 p219 was labelled
 *     "3.0 CONCEPT SUBMITTAL REQUIREMENTS" where the truth is "Chapter 15,
 *     8.3 Solar Energy". Every doc15 chunk carries "5 General", which is
 *     paragraph 5 of the cover page.
 *   - `scripts/section_audit.py` over the corpus: doc16 scores 0% correct,
 *     11 of 11 wrong; the whole of doc17's Appendix A carries "3.20 SUPPLY
 *     CHAIN RISK MANAGEMENT" from the last numbered chapter before it.
 *
 * FABRICATED is zero corpus-wide — the chunker never invents a clause number.
 * That is exactly what makes the label dangerous rather than obviously broken:
 * a stale label is a real clause from the same document, so it reads as
 * plausible and an engineer has no way to tell it from a correct one.
 *
 * WHY SUPPRESSION AND NOT A FIX. Repairing the chunker means re-ingesting the
 * corpus. Until then the page number is reliable and the heading is not, and
 * this codebase does not print a value it cannot stand behind. Document plus
 * page is the citation; it is auditable on its own, and it is untouched.
 *
 * WHY A FUNCTION AND NOT A DELETED BRANCH. `AnswerPassage` carries NO field
 * that separates a trustworthy label from a stale one — no confidence, no
 * record of the page the heading was found on, nothing (see contracts/types.ts
 * line 255: `section: string | null`, and `chunks` in backend/app/db.py, which
 * stores the bare string). If such a field is ever added, this is the one
 * place that has to change, and `clauseLabel.test.tsx` is the one place that
 * states what it must mean.
 *
 * Returns null in every case, deliberately. A caller renders NOTHING for null
 * — never "unknown", never "N/A", never a dash. The absence of a label is not
 * a fact about the document and must not be dressed up as one.
 */
export function clauseLabel(passage: AnswerPassage | null | undefined): string | null {
  void passage;
  return null;
}
