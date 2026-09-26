import type { AnswerabilityVerdict, EvidenceRef, ScopeAmbiguity, Understanding } from "../../types/api";

/**
 * B8/B9: what the answer-level safety gate said, in the reader's words.
 *
 * "supported" renders nothing - the answer card itself is the answer. Every
 * other verdict is a warning ABOVE the card, never a replacement for it: the
 * passages stay visible so the reader can judge for themselves.
 */
export const NOT_DETERMINED = "I cannot determine this from the available evidence";

const HEADLINE: Record<Exclude<AnswerabilityVerdict, "supported">, string> = {
  insufficient_evidence: NOT_DETERMINED,
  conflicting_evidence: "The documents disagree on this - compare the passages before relying on either",
  ambiguous_evidence: "This text appears in more than one document - check which one applies",
  requires_another_document: "The passage refers to another document that is not in the library",
  requires_engineer_review: "This needs an engineer's judgement - the passages are evidence, not a verdict",
};

export function evidenceLabel(ref: EvidenceRef): string | null {
  const parts: string[] = [];
  if (ref.page_start != null) {
    parts.push(ref.page_end != null && ref.page_end !== ref.page_start
      ? `pages ${ref.page_start}-${ref.page_end}` : `page ${ref.page_start}`);
  }
  if (ref.section) parts.push(ref.section);
  return parts.length ? parts.join(", ") : null;
}

export function VerdictNotice({ verdict, reason, evidence }: {
  verdict: AnswerabilityVerdict; reason: string; evidence: EvidenceRef[];
}) {
  if (verdict === "supported") return null;
  const labels = evidence.map(evidenceLabel).filter((l): l is string => l != null);
  return (
    <div role="status" data-verdict={verdict}
      className="rounded-[var(--radius-md)] border border-warn-500/50 bg-warn-500/10 p-3">
      <p className="text-sm font-semibold text-warn-500">{HEADLINE[verdict]}</p>
      {reason && <p className="mt-1 text-sm text-slateish-300">{reason}</p>}
      {labels.length > 0 && (
        <ul className="mt-1 text-xs text-slateish-400">
          {labels.map((l, i) => <li key={i}>{l}</li>)}
        </ul>
      )}
    </div>
  );
}

/** B6C: how the question was scoped, shown - a narrowed search is never silent. */
export function ScopeNotice({ understanding, ambiguity }: {
  understanding?: Understanding | null; ambiguity?: ScopeAmbiguity | null;
}) {
  const scoped = understanding?.scope_reason ?? null;
  const clause = understanding?.clause ?? null;
  const names = (ambiguity?.documents ?? []).map((d) => d.filename).filter((n): n is string => !!n);
  if (!scoped && !clause && !ambiguity) return null;
  return (
    <div className="space-y-1 text-xs text-slateish-400" data-testid="scope-notice">
      {scoped && <p>Searched: {scoped}</p>}
      {clause && <p>Clause asked about: {clause}</p>}
      {ambiguity && (
        <p className="text-warn-500">
          {ambiguity.reason}{names.length > 0 ? ` (${names.join(", ")})` : ""}
        </p>
      )}
    </div>
  );
}

/** A reopened turn that cited a document the reader can no longer open. */
export function WithheldNotice({ text }: { text: string | null }) {
  return (
    <div role="status" data-testid="withheld"
      className="rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4 text-sm text-slateish-400">
      {text}
    </div>
  );
}
