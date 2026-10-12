import type { AnswerabilityVerdict, ConditionChoice, EvidenceRef, ScopeAmbiguity, Understanding } from "../../types/api";

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
  conflicting_evidence: "The passages disagree on this - compare them before relying on either",
  ambiguous_evidence: "This text appears in more than one document - check which one applies",
  requires_another_document: "The passage refers to another document that is not in the library",
  requires_engineer_review: "This needs an engineer's judgement - the passages are evidence, not a verdict",
  depends_on_condition: "The value depends on a condition the question does not state - there is no single answer yet",
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

/**
 * Plan step 4: which clause applies. "options" is a warning the reader must
 * act on - the clauses set different values for different conditions and the
 * question did not say which; each is listed with its condition. "matched"
 * says why a clause other than the top-ranked one answers.
 */
export function ConditionNotice({ choice }: { choice?: ConditionChoice | null }) {
  if (!choice || choice.options.length === 0) return null;
  const where = (o: ConditionChoice["options"][number]) =>
    [o.section, o.page_start != null ? `page ${o.page_start}` : null].filter(Boolean).join(", ");
  if (choice.mode === "matched" && choice.within_passage) {
    return (
      <p className="text-xs text-slateish-400" data-testid="condition-matched">
        Answered for {choice.question_names.join(", ")}: this passage lists several cases; the line for{" "}
        {choice.options[0].conditions.join(", ")} is highlighted.
      </p>
    );
  }
  if (choice.mode === "matched") {
    return (
      <p className="text-xs text-slateish-400" data-testid="condition-matched">
        Answered for {choice.question_names.join(", ")}: the clause written for{" "}
        {choice.options[0].conditions.join(", ")} applies, not a higher-ranked clause for a different case.
      </p>
    );
  }
  return (
    <div role="status" data-testid="condition-options"
      className="rounded-[var(--radius-md)] border border-warn-500/50 bg-warn-500/10 p-3">
      <p className="text-sm font-semibold text-warn-500">
        Different values apply to different {choice.kinds.join(" / ")} - which applies to you?
      </p>
      {choice.within_passage && (
        <p className="mt-1 text-xs text-slateish-400">
          One passage lists every case{where(choice.options[0]) ? ` (${where(choice.options[0])})` : ""}:
        </p>
      )}
      <ul className="mt-1 space-y-0.5 text-sm text-slateish-300">
        {choice.options.map((o, i) => (
          <li key={`${o.chunk_id}:${i}`}>
            <span className="font-medium">{o.conditions.join(", ")}</span>
            {choice.within_passage && o.line
              ? <span className="text-slateish-400"> - "{o.line}"</span>
              : where(o) && <span className="text-slateish-400"> - {where(o)}</span>}
          </li>
        ))}
      </ul>
      <p className="mt-1 text-xs text-slateish-400">Ask again naming the {choice.kinds.join(" / ")} to get one answer.</p>
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
