/**
 * R21 (#785): the two pages a finding rests on, next to each other.
 *
 * ONE SCREEN, BOTH SIDES. An engineer deciding a CRS row needs the line the
 * contractor wrote and the clause it is held against at the same time;
 * opening one, closing it and opening the other is how a page gets misread.
 * Left: the submittal at the cited page, with the value as read. Right: the
 * standard at the cited page, with the requirement as stored. Both texts are
 * shown verbatim - a summary here would hide the part being judged.
 *
 * A SIDE THAT CANNOT BE SHOWN SAYS WHY, in its own pane: no cited page, or a
 * document this screen could not open. It is never filled with the other
 * side's page or left blank, because an empty pane reads as "nothing there".
 *
 * #508: each page comes from the finding's evidence route, which boxes the
 * finding's own stored text on it - or says it could not, and draws nothing.
 */
import type { DocumentRecord, ReviewFinding, ReviewRunStandard } from "../../types/api";
import { EvidencePageImage } from "./EvidencePageImage";
import { orNothing } from "./reviewFormat";

export interface SideBySideEvidenceProps {
  finding: ReviewFinding;
  submittal: DocumentRecord | null;
  standard: DocumentRecord | null;
  standardName?: string;
  onClose: () => void;
}

export function SideBySideEvidence(
  { finding, submittal, standard, standardName, onClose }: SideBySideEvidenceProps,
) {
  return (
    <section
      aria-label="Submittal and standard side by side"
      className="rounded-[var(--radius-md)] border border-ink-700 bg-ink-900 p-3"
    >
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm text-slateish-300">Submittal and standard, side by side</p>
        <button
          type="button" onClick={onClose}
          className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-1 text-xs text-slateish-300"
        >Close</button>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <Pane
          side="Submittal" findingId={finding.id}
          document={submittal}
          name={submittal?.filename}
          page={finding.contractor_page ?? null}
          label={finding.contractor_section ? `Read: ${finding.contractor_section}` : "Read"}
          text={orNothing(finding.contractor_evidence_text) || null}
          emptyText="No value was read from the submittal for this requirement."
        />
        <Pane
          side="Standard" findingId={finding.id}
          document={standard}
          name={standard?.filename ?? standardName}
          page={finding.standard_page ?? null}
          label={finding.standard_clause ? `Clause ${finding.standard_clause}` : "Requirement"}
          text={orNothing(finding.requirement_source_text) || orNothing(finding.requirement) || null}
          emptyText="No requirement text is stored for this finding."
        />
      </div>
    </section>
  );
}

function Pane({ side, findingId, document, name, page, label, text, emptyText }: {
  side: "Submittal" | "Standard";
  findingId: string;
  document: DocumentRecord | null;
  name?: string;
  page: number | null;
  label: string;
  text: string | null;
  emptyText: string;
}) {
  return (
    <div role="group" aria-label={side} className="flex min-w-0 flex-col gap-2">
      <div>
        <h5 className="text-xs uppercase tracking-wide text-slateish-400">{side}</h5>
        <p className="text-sm text-slateish-200">
          {name ?? ""}{page ? ` — page ${page}` : ""}
        </p>
        <p className="mt-1 text-xs text-slateish-400">{label}</p>
        <p className="whitespace-pre-wrap text-sm text-slateish-100">{text ?? emptyText}</p>
      </div>
      {document && page ? (
        <EvidencePageImage
          findingId={findingId}
          side={side === "Submittal" ? "submittal" : "standard"}
          page={page}
        />
      ) : (
        <p className="rounded-[var(--radius-sm)] border border-dashed border-ink-600 p-3 text-xs text-slateish-500">
          {/* WHY THE PAGE IS MISSING, not a blank box: a pane with nothing
              in it reads as "the page is empty". */}
          {!page
            ? `The finding cites no ${side.toLowerCase()} page, so there is no page to show.`
            : "The cited document could not be opened from this screen."}
        </p>
      )}
    </div>
  );
}

/** Why the review applied this finding's standard, as the run recorded it.
 *  The reason and the evidence are printed verbatim (a re-worded semantic
 *  match would read as a citation it is not). A finding with no standard - a
 *  datasheet checklist item - shows nothing; a standard the run holds no
 *  record for says so. `entry` undefined means the run's standards have not
 *  loaded yet: that is said as loading, never as "no record". */
export function WhyStandardApplies({ finding, entry }: {
  finding: ReviewFinding;
  entry: ReviewRunStandard | null | undefined;
}) {
  if (!finding.standard_document_id) return null;
  return (
    <div data-testid="why-standard-applies">
      <h4 className="text-xs uppercase tracking-wide text-slateish-400">Why this standard applies</h4>
      {entry === undefined ? (
        <p className="mt-1 text-sm text-slateish-400">Loading the run's standards…</p>
      ) : entry ? (
        <div className="mt-1 space-y-1 text-sm text-slateish-200">
          <p>
            <span className="rounded-full border border-ink-600 bg-ink-800 px-2 py-0.5 text-xs text-slateish-300">
              {entry.selection_method ?? "unrecorded"}
            </span>
            {entry.selection_reason ? <span className="ml-2">{entry.selection_reason}</span> : null}
          </p>
          {entry.evidence_quote && (
            <p className="text-xs text-slateish-400">
              Evidence{entry.evidence_page != null ? `, page ${entry.evidence_page}` : ""}: “{entry.evidence_quote}”
            </p>
          )}
          {entry.scope_decision && (
            <p className="text-xs text-slateish-400">Scope decision: {entry.scope_decision}</p>
          )}
        </div>
      ) : (
        <p className="mt-1 text-sm text-slateish-400">
          This run holds no record of why this standard was selected.
        </p>
      )}
      <RequirementScope finding={finding} />
    </div>
  );
}

/** R21: why THIS requirement applies (or not) here, from the run's own scope
 *  ledger, verbatim, with who decided. Nothing when the run recorded none:
 *  the standard-level reason above is then the only one there is. */
function RequirementScope({ finding }: { finding: ReviewFinding }) {
  const decision = finding.scope_decision;
  if (!decision) return null;
  return (
    <p data-testid="requirement-scope" className="text-xs text-slateish-300">
      This requirement: {decision.reason}
      <span className="ml-1 text-slateish-500">(decided by {decision.decided_by})</span>
    </p>
  );
}
