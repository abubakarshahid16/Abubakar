/**
 * The consolidated summary of a comprehensive analysis.
 *
 * Everything in this card is GENERATED PROSE - the model's words, never the
 * document's. It therefore renders in the Tier 2 style from AnswerCard: sans
 * type, amber rule, labelled "written by the model". The document's own words
 * live in the evidence ledger, in serif on a quote rule, and nothing here may
 * look like them.
 *
 * The header counts PASSAGES, never documents. A summary built from three
 * evidence items cites three passages; claiming it covers "3 documents" would
 * assert a breadth of reading that never happened.
 *
 * A null summary renders NOTHING for the prose. If the build declares that
 * synthesis is not implemented, that is said in one line - a named omission,
 * never an empty card that reads as "the model had nothing to add".
 */
import type { AnalysisResult, DocumentedFinding } from "../../types/analysis";

/**
 * WHY THE MARKER READS "S4" AND NOT "4".
 *
 * `[S4]` used to render as a pill containing the bare digit `4`. That was
 * survivable while the model put its markers at the END of a sentence - the
 * digit sat after a full stop and nothing followed it. It stopped being
 * survivable the day the model began writing the marker FIRST:
 *
 *   "[S4] mandates that all contract drawings be developed using CADD"
 *
 * rendered as "4 mandates that all contract drawings...". The pill was still
 * there, still a button, still clickable - but a small number pressed against
 * prose is read as a quantity, not as a citation, and the summary looked like
 * broken text. It also copies and reads aloud that way: the accessible name
 * carried "Show source 4" but the TEXT of the run was "4 mandates".
 *
 * The renderer was never position-dependent (the regex below has always matched
 * anywhere in the string), so the position was not the bug. The bug was that
 * the marker's own glyphs were a number and nothing else. They now carry the
 * source letter, so no marker can be mistaken for a quantity at any position,
 * and the pill carries a ring so it is a marked object rather than tinted text.
 * "30 percent" is prose and stays prose: only a literal `[S<digits>]` becomes a
 * marker, and a number the model merely wrote is never touched.
 */
function markerLabel(n: number): string {
  return `S${n}`;
}

function chipClass(): string {
  return "mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-[var(--radius-xs)] px-1 align-baseline font-mono text-xs leading-none bg-ink-700 text-slateish-300 ring-1 ring-ink-500 hover:bg-ink-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal-400";
}

/**
 * A citation marker whose index has an evidence id behind it.
 *
 * `label` exists because the two callers count in DIFFERENT vocabularies and
 * must not borrow each other's. In generated prose `n` IS the model's own
 * source number, so the marker reads "S4" and means [S4]. In a documented
 * finding `n` is a position within THAT finding's `citation_ids` - finding 2's
 * first citation is "1" and has nothing to do with the summary's [S1] - so it
 * reads "source 1". Labelling the finding's chips "S1" would assert a number
 * the API never gave them, next to claim text that may itself contain a real
 * "[S4]". Neither is ever a bare digit: a lone number pressed against prose is
 * read as a quantity, which is the defect this file was rewritten for.
 */
function Chip({ n, label, onClick }: { n: number; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Show source ${n}`}
      title={`Source ${n}`}
      data-citation-marker={n}
      className={chipClass()}
    >
      {label}
    </button>
  );
}

/**
 * A marker the model wrote that points at no supplied source. Never a live
 * chip: a click that opened the wrong passage would be a fabricated citation
 * dressed as a real one. Struck through, and it says why.
 */
function DeadChip({ n }: { n: number }) {
  return (
    <span
      title="citation not among supplied sources"
      aria-label={`Citation ${n} is not among the supplied sources`}
      data-citation-marker={n}
      className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-[var(--radius-xs)] px-1 align-baseline font-mono text-xs leading-none line-through bg-danger-500/10 text-danger-500 ring-1 ring-danger-500/40"
    >
      {markerLabel(n)}
    </span>
  );
}

/** Generated prose with `[S1]` markers turned into chips over `evidenceIds`. */
export function CitedText({
  text,
  evidenceIds,
  onCite,
}: {
  text: string;
  evidenceIds: string[];
  onCite: (evidenceId: string) => void;
}) {
  const parts: React.ReactNode[] = [];
  const citation = /\[S(\d+)\]/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = citation.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const n = Number(match[1]);
    const id = evidenceIds[n - 1];
    parts.push(
      id ? (
        <Chip key={`${match.index}-${n}`} n={n} label={markerLabel(n)} onClick={() => onCite(id)} />
      ) : (
        <DeadChip key={`${match.index}-${n}`} n={n} />
      ),
    );
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}

function Finding({
  finding,
  onCite,
}: {
  finding: DocumentedFinding;
  onCite: (evidenceId: string) => void;
}) {
  const userStated = finding.source_kind === "user_stated";
  return (
    <li className="text-sm text-slateish-200">
      <span>{finding.claim}</span>
      {finding.citation_ids.length > 0 && (
        <span className="ms-1 inline-flex flex-wrap items-baseline">
          {finding.citation_ids.map((id, i) => (
            <Chip key={id} n={i + 1} label={`source ${i + 1}`} onClick={() => onCite(id)} />
          ))}
        </span>
      )}
      {userStated && (
        <span className="ms-2 rounded-[var(--radius-xs)] border border-warn-500/50 px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider text-warn-500">
          stated by the user — not documentary evidence
        </span>
      )}
      {finding.text_source === "recognised" && (
        <span className="ms-2 text-xs uppercase tracking-wider text-slateish-500">
          from recognised (OCR) text
        </span>
      )}
    </li>
  );
}

export function SummaryCard({
  result,
  onCite,
  onSuggestCorrection,
}: {
  result: AnalysisResult;
  onCite: (evidenceId: string) => void;
  onSuggestCorrection?: () => void;
}) {
  const ids = result.summary_cited_evidence_ids;
  const n = ids.length;
  const hasFindings = result.documented_findings.length > 0;

  // Nothing at all to say: no prose and no findings. Renders as NOTHING - the
  // same rule as a null coverage verdict. A line saying the summary is absent
  // would be a claim about why, and this card does not know why.
  //
  // Until stage 3 there was a branch here saying "Generated summary is not
  // available in this build", shown when not_implemented_sections carried
  // "synthesis". Synthesis exists now, the API never sends that value, and the
  // sentence was false the moment it landed - so it is gone rather than
  // stranded behind a condition that can no longer be true.
  if (result.summary === null && !hasFindings) return null;

  return (
    <section
      aria-labelledby="summary-card-heading"
      className="card-3d accent-edge relative surface-card rounded-[var(--radius-md)] border border-info-500/30 bg-info-500/[0.05] p-4"
    >
      {result.summary !== null ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p
              id="summary-card-heading"
              className="text-xs font-semibold uppercase tracking-wider text-info-500"
            >
              Written by the model — not the document's words
            </p>
            <span className="font-mono text-xs text-slateish-500">
              Summary of {n} passage{n === 1 ? "" : "s"}
            </span>
          </div>

          <p className="model-prose mt-2 text-[15px] text-slateish-200">
            <CitedText text={result.summary} evidenceIds={ids} onCite={onCite} />
          </p>

          {result.summary_truncated && (
            <p className="mt-2 rounded-[var(--radius-xs)] border border-warn-500/40 bg-warn-500/[0.08] px-2.5 py-1.5 text-xs text-warn-500">
              This summary reached its length limit and stops early — the model had
              more to say. The passages it cites are complete; open them for the rest.
            </p>
          )}
          {(result.evidence_removed ?? []).length > 0 && (
            <div role="status" className="mt-2 rounded-[var(--radius-xs)] border border-warn-500/40 bg-warn-500/[0.08] px-2.5 py-1.5 text-xs text-warn-500">
              <p>
                {(result.evidence_removed ?? []).length === 1
                  ? "One source was shortened or left out before the summary was written."
                  : `${(result.evidence_removed ?? []).length} sources were shortened or left out before the summary was written.`}
              </p>
              <ul className="mt-1 space-y-0.5">
                {(result.evidence_removed ?? []).map((item) => (
                  <li key={`${item.index}-${item.filename ?? "source"}`}>
                    {item.filename ?? "A source"}{item.page_start !== null ? ` · page ${item.page_start}` : ""} — {item.action === "dropped" ? "not used" : `${item.characters_dropped.toLocaleString()} characters omitted`}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      ) : (
        <p id="summary-card-heading" className="sr-only">
          Documented findings
        </p>
      )}

      {hasFindings && (
        <div className={result.summary !== null ? "mt-3 border-t border-ink-700/60 pt-3" : ""}>
          <p className="text-xs uppercase tracking-wide text-slateish-500">Documented findings</p>
          <ul className="mt-1.5 space-y-1.5">
            {result.documented_findings.map((f, i) => (
              <Finding key={`${i}-${f.claim.slice(0, 32)}`} finding={f} onCite={onCite} />
            ))}
          </ul>
        </div>
      )}

      {onSuggestCorrection && (
        <div className="mt-3 border-t border-ink-700/60 pt-3">
          <button
            type="button"
            onClick={onSuggestCorrection}
            className="rounded-[var(--radius-xs)] border border-ink-500 px-3 py-1.5 text-sm text-slateish-200 hover:bg-ink-700"
          >
            Suggest correction
          </button>
        </div>
      )}
    </section>
  );
}
