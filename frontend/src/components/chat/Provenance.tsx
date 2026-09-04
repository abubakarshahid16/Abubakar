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
import type { AnswerPassage } from "../../types/api";

/** The wording that may ONLY appear over text from the PDF's own text layer. */
export const VERBATIM_STRINGS = [
  "Quoted verbatim from the document",
  "quoted directly, no AI rewriting",
] as const;

/** Read off a page image rather than out of the text layer. */
export function isRecognised(p: AnswerPassage | null | undefined): boolean {
  return p?.text_source === "recognised";
}

/** A recognised passage whose recogniser emitted characters the document's
 *  script cannot contain. PROOF of a substitution, not an opinion about one:
 *  two passages can both sit at 0.95 confidence and one of them contains 凤. */
export function hasAlphabetViolation(p: AnswerPassage | null | undefined): boolean {
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
  passage: AnswerPassage;
  variant?: "full" | "short";
}) {
  if (!isRecognised(passage)) return null;
  const violated = hasAlphabetViolation(passage);

  if (variant === "short") {
    return (
      <span
        className="rounded bg-warn-500/15 px-1.5 py-0.5 text-[11px] font-medium text-warn-500"
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
    <p className="text-[11px] font-semibold uppercase tracking-wider text-warn-500">
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
export function OcrConfidence({ passage }: { passage: AnswerPassage }) {
  if (!isRecognised(passage) || passage.ocr_min_conf == null) return null;
  return (
    <span
      className="font-mono text-[11px] text-slateish-500"
      title="Lowest OCR confidence across this passage. No pass/fail threshold is set - this is the measurement, not a verdict."
    >
      OCR confidence {passage.ocr_min_conf.toFixed(2)}
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
