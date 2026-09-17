/**
 * The preliminary gap assessment.
 *
 * The baseline must come from the user (docs/design-analysis-and-synthesis.md,
 * "Gap analysis"): no document carries a revision or approval status, so the
 * system cannot decide which one is the requirement. A typed requirement is THE
 * REQUIREMENT, not evidence - it is labelled as stated by the user and carries no
 * citation.
 *
 * Statuses are text plus an icon, never colour alone. "met" is rendered only
 * when the backend says so - it requires positive matching evidence, and there
 * is deliberately no code path here that derives it from an absence.
 * "possible_gap" is worded as possible: retrieval finding nothing is not proof
 * the documents say nothing.
 *
 * `baseline_span` is the document's own words (or the user's stated
 * requirement), set in serif on a quote rule so it is never mistaken for prose.
 */
import { useId, useState, type FormEvent } from "react";

import type { BaselineSelection, GapAnalysis, GapItem, GapItemStatus } from "../../types/analysis";
import type { EvidenceItem, ReviewCategory, ReviewFindingCreate, ReviewSeverity, ReviewTemplate } from "../../types/api";

const REVIEW_SENTENCE = "Review and approval by a qualified engineer is required.";

/**
 * The facet is a machine-derived grouping key, not a title.
 *
 * On real runs it arrives as "documents", "documents (%)", "section 4" - the
 * intersection of query terms, which is a known backend defect and is being
 * fixed there. This component may not invent a better one, so it stops the
 * meaningless string being the loudest thing in the row instead: the facet is
 * demoted to a small monospace marker behind the word "Facet", and the
 * baseline passage - the document's own words, by far the most informative
 * thing present - becomes the row's primary content. The string is printed
 * exactly as sent; only its prominence changed.
 */
const FACET_LABEL = "Facet";

/**
 * A caption is the COMPONENT'S OWN words, not the payload's, so it may be
 * printed only where it is true of the row in front of the reader.
 *
 * Both captions here are claims about how much project evidence the row
 * carries, and each was being printed on every row of its status regardless.
 * "Retrieval found nothing addressing this" appeared directly above three
 * evidence chips - a sentence the row itself disproves, on the one screen
 * whose job is saying what is and is not established. `captionRequires`
 * states the condition the sentence asserts; when the row does not meet it,
 * the sentence is WITHHELD rather than reworded, because the component has no
 * basis for a replacement. The row still carries its status, its baseline
 * passage, its evidence and the backend's own note.
 *
 * This changes nothing about what a status MEANS. "That is not proof the
 * documents say nothing" is deliberate and stays exactly as written, on the
 * rows where retrieval did in fact return nothing.
 */
type CaptionCondition = "no_project_evidence" | "project_evidence";

/**
 * `rank` is reading order, not severity arithmetic: a reader scanning for
 * problems should meet them first. `badge` is the chip's own tint, assembled
 * only from class strings already in use elsewhere in this codebase. It is
 * decoration - `text` is the carrier, and every status is legible with the
 * colour removed (section 9). `countWord` is how the status is counted in the
 * tally line; it is the status's own name, never a softer one.
 */
const STATUS: Record<
  GapItemStatus,
  {
    icon: string;
    text: string;
    tone: string;
    badge: string;
    rank: number;
    countWord: { one: string; many: string };
    caption: string | null;
    captionRequires: CaptionCondition | null;
  }
> = {
  met: {
    icon: "✓",
    text: "Met",
    tone: "text-signal-400",
    badge: "bg-signal-500/15 text-signal-400",
    rank: 3,
    countWord: { one: "met", many: "met" },
    caption: "Positive matching evidence was found.",
    // Asserts a presence. On a row citing nothing it is unsupported.
    captionRequires: "project_evidence",
  },
  possible_gap: {
    icon: "▲",
    text: "Possible gap",
    tone: "text-warn-500",
    badge: "bg-warn-500/15 text-warn-500",
    rank: 1,
    countWord: { one: "possible gap", many: "possible gaps" },
    caption: "Retrieval found nothing addressing this. That is not proof the documents say nothing.",
    // Asserts an absence. On a row carrying evidence chips it is false.
    captionRequires: "no_project_evidence",
  },
  conflict: {
    icon: "✕",
    text: "Conflict",
    tone: "text-danger-500",
    badge: "bg-danger-500/15 text-danger-500",
    rank: 0,
    countWord: { one: "conflict", many: "conflicts" },
    caption: null,
    captionRequires: null,
  },
  insufficient_evidence: {
    icon: "?",
    text: "Insufficient evidence",
    tone: "text-slateish-400",
    badge: "bg-ink-700 text-slateish-300",
    rank: 2,
    countWord: { one: "with insufficient evidence", many: "with insufficient evidence" },
    caption: null,
    captionRequires: null,
  },
  not_applicable: {
    icon: "—",
    text: "Not applicable",
    tone: "text-slateish-500",
    badge: "bg-ink-700 text-slateish-400",
    rank: 4,
    countWord: { one: "not applicable", many: "not applicable" },
    caption: null,
    captionRequires: null,
  },
};

/** The reading order of the statuses, most-attention-first. */
const STATUS_ORDER: GapItemStatus[] = (Object.keys(STATUS) as GapItemStatus[]).sort(
  (a, b) => STATUS[a].rank - STATUS[b].rank,
);

/**
 * `baseline_span` is typed as a string, but a run can put an empty one on a
 * row - three of the rows in the reported screen carried the label
 * "Baseline, quoted verbatim" over nothing at all. A label over nothing is
 * the same defect class already fixed elsewhere on this screen, so the label,
 * the quote rule and the "Show baseline passage" control are all withheld
 * together when there is no passage to show. Nothing is substituted for it.
 */
function hasBaselineSpan(item: GapItem): boolean {
  return typeof item.baseline_span === "string" && item.baseline_span.trim() !== "";
}

/** The backend's note, if it sent one with words in it. An empty string is not
 *  a note, and rendering it produces a blank paragraph - a null rendering as
 *  something. */
function noteOf(item: GapItem): string | null {
  return typeof item.note === "string" && item.note.trim() !== "" ? item.note : null;
}

/** The facet marker is a LABEL - the word "Facet" is this component's own.
 *  Printed over an empty string it is the "Baseline, quoted verbatim" defect
 *  again, so the whole marker is withheld when the payload sent no facet. */
function hasFacet(item: GapItem): boolean {
  return typeof item.facet === "string" && item.facet.trim() !== "";
}

/**
 * Does this row have anything of its own to put in front of a reader?
 *
 * A bullet that renders to nothing but its status is a count over nothing:
 * the collapsed summary already says "N facets not applicable", and the tally
 * line already says how many rows carry each status, so a row whose facet,
 * passage, evidence and note are all absent repeats a number the reader has
 * and adds not one word to it. Such a row is NOT rendered as a bullet; it is
 * disclosed in one line instead (see `withheldLine`), the same way the
 * summary's dropped sentences are.
 *
 * The caption counts as content because it is a sentence the reader gets
 * nowhere else on the row. Everything else here is the payload's.
 */
function hasRenderableBody(item: GapItem): boolean {
  return (
    hasFacet(item) ||
    hasBaselineSpan(item) ||
    item.project_citation_ids.length > 0 ||
    noteOf(item) !== null ||
    captionFor(item.status, item.project_citation_ids.length) !== null
  );
}

/** What was withheld and why, in the payload's terms, never invented. Mirrors
 *  the wording already used for the summary's dropped sentences. */
function withheldLine(n: number): string {
  return n === 1
    ? "One of them was reported with no facet, no passage, no evidence and no note, so it is not shown here."
    : `${n} of them were reported with no facet, no passage, no evidence and no note, so they are not shown here.`;
}

/**
 * Rows in the order a reader should meet them: by status rank, and within a
 * status the rows that cite project evidence before the rows that cite none.
 * A stable sort, so rows the payload cannot distinguish keep the payload's
 * order. This reorders; it adds and removes nothing.
 */
function orderedItems(items: GapItem[]): GapItem[] {
  return items
    .map((item, i) => ({ item, i }))
    .sort((a, b) => {
      const byStatus = STATUS[a.item.status].rank - STATUS[b.item.status].rank;
      if (byStatus !== 0) return byStatus;
      const aEvidence = a.item.project_citation_ids.length === 0 ? 1 : 0;
      const bEvidence = b.item.project_citation_ids.length === 0 ? 1 : 0;
      if (aEvidence !== bEvidence) return aEvidence - bEvidence;
      return a.i - b.i;
    })
    .map((x) => x.item);
}

/**
 * A tally, not a verdict. Every number is a count of rows actually present and
 * every word is the status's own name; there is no total, no score, no
 * percentage and no adjective, because the data supports none of those. A
 * status with no rows is not mentioned rather than printed as a zero.
 */
function tallyLine(items: GapItem[]): string {
  const head = `${items.length} ${items.length === 1 ? "facet" : "facets"} compared`;
  const parts = STATUS_ORDER.flatMap((status) => {
    const n = items.filter((it) => it.status === status).length;
    if (n === 0) return [];
    const w = STATUS[status].countWord;
    return [`${n} ${n === 1 ? w.one : w.many}`];
  });
  return [head, ...parts].join(" · ");
}

/** The caption for this row, or null when the row does not bear it out. */
function captionFor(status: GapItemStatus, projectEvidenceCount: number): string | null {
  const s = STATUS[status];
  if (s.caption === null) return null;
  if (s.captionRequires === "no_project_evidence" && projectEvidenceCount !== 0) return null;
  if (s.captionRequires === "project_evidence" && projectEvidenceCount === 0) return null;
  return s.caption;
}

function StatusMark({ status }: { status: GapItemStatus }) {
  const s = STATUS[status];
  return (
    <span
      className={[
        "inline-flex items-center rounded-[var(--radius-xs)] px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider",
        s.badge,
      ].join(" ")}
    >
      <span aria-hidden="true" className="mr-1 font-mono">
        {s.icon}
      </span>
      {s.text}
    </span>
  );
}

function EvidenceChip({
  n,
  evidenceId,
  onCite,
  selectedEvidenceId: _selectedEvidenceId,
}: {
  n: number;
  evidenceId: string;
  onCite: (evidenceId: string) => void;
  selectedEvidenceId?: string | null;
}) {
  return (
    <button
      type="button"
      onClick={() => onCite(evidenceId)}
      aria-label={`Show project evidence ${n}`}
      className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-[var(--radius-xs)] bg-ink-700 px-1 align-baseline font-mono text-[11px] leading-none text-slateish-300 hover:bg-ink-600"
    >
      {n}
    </button>
  );
}

function BaselineHeader({
  baseline,
  documents,
}: {
  baseline: BaselineSelection | null;
  documents: { id: string; filename: string }[];
}) {
  if (baseline === null) return null;
  if (baseline.kind === "stated_requirement") {
    return (
      <div className="mt-2 text-sm">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-warn-500">
          Baseline &mdash; stated by the user. Not evidence; carries no citation.
        </p>
        <p className="mt-1 text-slateish-200">{baseline.text}</p>
      </div>
    );
  }
  // The filename, the way every other surface in this app names a document. A
  // raw `doc_4e2b...` tells the reader nothing about which document is the
  // requirement. `documents` is the run's own evidence, so a baseline the run
  // retrieved nothing from is not in it: the identifier is shown then, WITH
  // the reason it is an identifier, never bare.
  const filename = documents.find((d) => d.id === baseline.document_id)?.filename ?? null;
  return (
    <div className="mt-2 text-sm">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-signal-400">Baseline</p>
      <p className="mt-1 text-slateish-200">
        {filename ?? baseline.document_id}
        {baseline.section !== null && <span className="text-slateish-400"> &sect; {baseline.section}</span>}
      </p>
      {filename === null && baseline.document_id !== null && (
        <p className="mt-1 text-xs text-slateish-500">
          Shown as an identifier: this run cited no passage from that document, so its filename
          is not among the evidence returned.
        </p>
      )}
    </div>
  );
}

function ItemRow({
  item,
  onCite,
  baselineIsStated,
  baselineDocumentId,
  ledger,
  onCreateFinding,
  templates,
}: {
  item: GapItem;
  onCite: (evidenceId: string) => void;
  baselineIsStated: boolean;
  baselineDocumentId: string | null;
  ledger: EvidenceItem[];
  onCreateFinding?: (draft: ReviewFindingCreate) => Promise<void> | void;
  templates: ReviewTemplate[];
}) {
  const s = STATUS[item.status];
  const evidenceCount = item.project_citation_ids.length;
  const caption = captionFor(item.status, evidenceCount);
  const withSpan = hasBaselineSpan(item);
  const note = noteOf(item);
  const [editing, setEditing] = useState(false);
  const [category, setCategory] = useState<ReviewCategory>(
    item.status === "conflict" ? "inconsistency" : item.status === "possible_gap" ? "missing_information" : "requirement_deviation",
  );
  const [severity, setSeverity] = useState<ReviewSeverity>(
    item.status === "conflict" ? "major" : item.status === "possible_gap" ? "minor" : "observation",
  );
  const [saveError, setSaveError] = useState<string | null>(null);
  const [action, setAction] = useState("Review the cited evidence and record the engineering disposition.");
  const [templateId, setTemplateId] = useState("");
  const targetEvidence = ledger.find((e) => item.project_citation_ids.includes(e.evidence_id));

  async function saveFinding(e: FormEvent) {
    e.preventDefault();
    if (!onCreateFinding || !targetEvidence) return;
    setSaveError(null);
    try {
      await onCreateFinding({
        document_id: targetEvidence.document_id,
        baseline_document_id: baselineDocumentId,
        category,
        severity,
        requirement: item.baseline_span || item.facet || "Requirement requires engineering review",
        finding: note || `${STATUS[item.status].text}: ${item.facet || "review item"}`,
        required_action: action.trim() || "Review the cited evidence and record the engineering disposition.",
        template_id: templateId || null,
        citation_ids: [item.baseline_citation_id, ...item.project_citation_ids].filter((id): id is string => Boolean(id)),
      });
      setEditing(false);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "The finding could not be saved.");
    }
  }
  return (
    <li className="border-t border-ink-700/60 py-3 first:border-t-0">
      {/* The status leads the row; the facet trails it as a marker. See the
          note on FACET_LABEL for why the facet is not the heading. The marker
          is withheld entirely when there is no facet: the word "Facet" over an
          empty string is a label over nothing. */}
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <StatusMark status={item.status} />
        {hasFacet(item) && (
          <span className="text-[11px] text-slateish-500">
            {FACET_LABEL}{" "}
            <span data-facet="" className="font-mono text-slateish-400">
              {item.facet}
            </span>
          </span>
        )}
      </div>

      {withSpan && (
        <>
          <p className="mt-1.5 text-[11px] uppercase tracking-wide text-slateish-500">
            {baselineIsStated ? "Requirement as stated by the user" : "Baseline, quoted verbatim"}
          </p>
          <blockquote
            className={[
              "mt-1 whitespace-pre-wrap py-2 pl-4 pr-3 text-[14px] text-slateish-100",
              baselineIsStated
                ? "model-prose border-l-2 border-warn-500/60 bg-warn-500/[0.06]"
                : "document-quote border-l-2 border-signal-500/60 bg-ink-900",
            ].join(" ")}
          >
            {item.baseline_span}
          </blockquote>
          {item.baseline_citation_id !== null && (
            <div className="mt-1 text-xs text-slateish-400">
              <button
                type="button"
                onClick={() => onCite(item.baseline_citation_id as string)}
                className="underline decoration-ink-500 underline-offset-2 hover:decoration-slateish-300"
              >
                Show baseline passage
              </button>
            </div>
          )}
        </>
      )}

      <div className="mt-2 flex flex-wrap items-baseline gap-x-2 text-xs text-slateish-400">
        <span>Project evidence:</span>
        {evidenceCount === 0 ? (
          <span className="text-slateish-500">none cited</span>
        ) : (
          item.project_citation_ids.map((id, i) => (
            <EvidenceChip key={id} n={i + 1} evidenceId={id} onCite={onCite} />
          ))
        )}
      </div>

      {note !== null && <p className="mt-2 text-sm text-slateish-300">{note}</p>}
      {caption !== null && <p className={["mt-1.5 text-xs", s.tone].join(" ")}>{caption}</p>}
      {onCreateFinding && (
        targetEvidence ? (
          <div className="mt-2">
            <button
              type="button"
              onClick={() => setEditing((open) => !open)}
              className="rounded-[var(--radius-xs)] border border-signal-500/50 px-2.5 py-1 text-xs text-signal-300 hover:bg-signal-500/10"
            >
              {editing ? "Cancel review finding" : "Add review finding"}
            </button>
            {editing && (
              <form onSubmit={(e) => void saveFinding(e)} className="mt-2 space-y-2 rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 p-3">
                <p className="text-xs text-slateish-400">Save this evidence-backed item for engineering assignment and response.</p>
                {templates.length > 0 && <label className="block text-xs text-slateish-400">Review template
                  <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} className="mt-1 w-full rounded-[var(--radius-xs)] border border-ink-600 bg-ink-850 px-2 py-1.5 text-sm text-slateish-200">
                    <option value="">No template selected</option>
                    {templates.map((template) => <option key={template.id} value={template.id}>{template.name} · v{template.version}</option>)}
                  </select>
                </label>}
                {templateId && (() => { const selected = templates.find((item) => item.id === templateId); return selected && selected.governing_sources.length > 1 ? <p className="rounded-[var(--radius-xs)] border border-warn-500/40 bg-warn-500/10 px-2 py-1.5 text-xs text-warn-500">Multiple governing sources are attached. Confirm which source controls if they conflict: {selected.governing_sources.join("; ")}</p> : null; })()}
                <div className="grid gap-2 sm:grid-cols-2">
                  <label className="text-xs text-slateish-400">Category
                    <select value={category} onChange={(e) => setCategory(e.target.value as ReviewCategory)} className="mt-1 w-full rounded-[var(--radius-xs)] border border-ink-600 bg-ink-850 px-2 py-1.5 text-sm text-slateish-200">
                      <option value="missing_information">Missing information</option>
                      <option value="inconsistency">Inconsistency</option>
                      <option value="requirement_deviation">Requirement deviation</option>
                      <option value="document_control">Document control</option>
                      <option value="technical_query">Technical query</option>
                      <option value="positive_observation">Positive observation</option>
                    </select>
                  </label>
                  <label className="text-xs text-slateish-400">Severity
                    <select value={severity} onChange={(e) => setSeverity(e.target.value as ReviewSeverity)} className="mt-1 w-full rounded-[var(--radius-xs)] border border-ink-600 bg-ink-850 px-2 py-1.5 text-sm text-slateish-200">
                      <option value="critical">Critical</option>
                      <option value="major">Major</option>
                      <option value="minor">Minor</option>
                      <option value="observation">Observation</option>
                    </select>
                  </label>
                </div>
                <label className="block text-xs text-slateish-400">Required action
                  <textarea value={action} onChange={(e) => setAction(e.target.value)} rows={2} className="mt-1 w-full rounded-[var(--radius-xs)] border border-ink-600 bg-ink-850 px-2 py-1.5 text-sm text-slateish-200" />
                </label>
                <button type="submit" className="rounded-[var(--radius-xs)] bg-signal-500/20 px-3 py-1.5 text-xs font-medium text-signal-300 ring-1 ring-signal-500/50 hover:bg-signal-500/30">Save finding</button>
                {saveError !== null && <p className="text-xs text-danger-500" role="alert">{saveError}</p>}
              </form>
            )}
          </div>
        ) : (
          <p className="mt-2 text-xs text-slateish-500">No submitted-document citation is available to create a workflow finding.</p>
        )
      )}
    </li>
  );
}

function NominateBaseline({
  documents,
  onNominate,
}: {
  documents: { id: string; filename: string }[];
  onNominate: (b: BaselineSelection) => void;
}) {
  const [documentId, setDocumentId] = useState("");
  const [section, setSection] = useState("");
  const [text, setText] = useState("");
  const selectId = useId();
  const sectionId = useId();
  const textId = useId();

  const typed = text.trim();
  const canSubmit = documentId !== "" || typed !== "";

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    if (documentId !== "") {
      const sec = section.trim();
      onNominate({
        kind: sec ? "document_section" : "document",
        document_id: documentId,
        section: sec || null,
        text: null,
      });
      return;
    }
    onNominate({ kind: "stated_requirement", document_id: null, section: null, text: typed });
  }

  return (
    <form onSubmit={submit} className="mt-3 space-y-3 rounded-[var(--radius-xs)] border border-ink-700 p-3">
      <p className="text-xs text-slateish-400">Nominate a baseline: a document (optionally a section), or state the requirement.</p>
      <div>
        <label htmlFor={selectId} className="block text-xs text-slateish-400">
          Baseline document
        </label>
        <select
          id={selectId}
          value={documentId}
          onChange={(e) => setDocumentId(e.target.value)}
          className="mt-1 w-full rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-slateish-200"
        >
          <option value="">&mdash; none &mdash;</option>
          {documents.map((d) => (
            <option key={d.id} value={d.id}>
              {d.filename}
            </option>
          ))}
        </select>
      </div>
      {documentId !== "" && (
        <div>
          <label htmlFor={sectionId} className="block text-xs text-slateish-400">
            Section (optional)
          </label>
          <input
            id={sectionId}
            type="text"
            value={section}
            onChange={(e) => setSection(e.target.value)}
            className="mt-1 w-full rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-slateish-200"
          />
        </div>
      )}
      <div>
        <label htmlFor={textId} className="block text-xs text-slateish-400">
          Or state the requirement
        </label>
        <textarea
          id={textId}
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={documentId !== ""}
          className="mt-1 w-full rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-slateish-200 disabled:opacity-60"
        />
        {typed !== "" && (
          <p className="mt-1 text-xs text-warn-500" aria-live="polite">
            This is the requirement, not evidence. It carries no citation.
          </p>
        )}
      </div>
      <button
        type="submit"
        disabled={!canSubmit}
        className="rounded-[var(--radius-xs)] border border-ink-500 px-3 py-1.5 text-sm text-slateish-200 hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        Use as baseline
      </button>
    </form>
  );
}

export function GapAnalysisCard({
  gaps,
  onNominateBaseline,
  documents,
  onCite,
  ledger,
  onCreateFinding,
  templates = [],
}: {
  gaps: GapAnalysis;
  onNominateBaseline?: (b: BaselineSelection) => void;
  documents: { id: string; filename: string }[];
  onCite: (evidenceId: string) => void;
  ledger?: EvidenceItem[];
  onCreateFinding?: (draft: ReviewFindingCreate) => Promise<void> | void;
  templates?: ReviewTemplate[];
}) {
  const heading = (
    <h3 className="text-[11px] font-semibold uppercase tracking-wider text-slateish-300">
      Preliminary gap assessment
    </h3>
  );

  if (gaps.applicability === "not_applicable") {
    return (
      <section aria-label="Gap analysis" className="card-3d surface-card rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4">
        {heading}
        <p className="mt-2 text-sm text-slateish-500">
          Gap analysis is not applicable: the question contains no comparison or baseline.
        </p>
      </section>
    );
  }

  if (gaps.applicability === "insufficient_baseline") {
    return (
      <section aria-label="Gap analysis" className="card-3d surface-card rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4" aria-live="polite">
        {heading}
        <p className="mt-2 text-sm text-slateish-300">
          Gap analysis needs a baseline &mdash; the document or requirement the others are checked
          against. None was nominated.
        </p>
        {onNominateBaseline && <NominateBaseline documents={documents} onNominate={onNominateBaseline} />}
        <p className="mt-3 border-t border-ink-700 pt-2 text-xs text-slateish-400">{REVIEW_SENTENCE}</p>
      </section>
    );
  }

  const baselineIsStated = gaps.baseline?.kind === "stated_requirement";
  const sorted = orderedItems(gaps.items);
  const orderedAll = sorted.filter((it) => it.status !== "not_applicable");
  const notApplicableAll = sorted.filter((it) => it.status === "not_applicable");
  // A row with nothing of its own to show is not rendered as a bullet; it is
  // counted, and then said out loud. See `hasRenderableBody`.
  const ordered = orderedAll.filter(hasRenderableBody);
  const notApplicable = notApplicableAll.filter(hasRenderableBody);
  const orderedWithheld = orderedAll.length - ordered.length;
  const notApplicableWithheld = notApplicableAll.length - notApplicable.length;

  return (
    <section aria-label="Gap analysis" className="card-3d surface-card rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4">
      {heading}
      <BaselineHeader baseline={gaps.baseline} documents={documents} />

      {gaps.items.length === 0 ? (
        <p className="mt-3 text-sm text-slateish-500">No gap items were produced for this baseline.</p>
      ) : (
        <>
          <p className="mt-3 border-t border-ink-700 pt-2 text-xs text-slateish-400">{tallyLine(gaps.items)}</p>
          {ordered.length > 0 && (
            <ul className="mt-1">
              {ordered.map((it, i) => (
                <ItemRow key={`${it.facet}-${i}`} item={it} onCite={onCite} baselineIsStated={baselineIsStated} baselineDocumentId={gaps.baseline?.document_id ?? null} ledger={ledger ?? []} onCreateFinding={onCreateFinding} templates={templates} />
              ))}
            </ul>
          )}
          {orderedWithheld > 0 && (
            <p className="mt-2 text-xs text-slateish-500">{withheldLine(orderedWithheld)}</p>
          )}
          {notApplicableAll.length > 0 && (
            /* Collapsed, never hidden: the count is in the summary, so it is
               readable without expanding, and every row is one click away. */
            <details className="mt-2 rounded-[var(--radius-xs)] border border-ink-700 bg-ink-850 px-3 py-2">
              {/* The count is of what the payload reported, not of what this
                  list could render - the honest number is the number that came
                  back. Where the two differ, `withheldLine` says so. */}
              <summary className="cursor-pointer text-xs text-slateish-400">
                {notApplicableAll.length} {notApplicableAll.length === 1 ? "facet" : "facets"} not
                applicable
              </summary>
              {notApplicable.length > 0 && (
                <ul className="mt-1">
                  {notApplicable.map((it, i) => (
                    <ItemRow
                      key={`na-${it.facet}-${i}`}
                      item={it}
                      onCite={onCite}
                      baselineIsStated={baselineIsStated}
                      baselineDocumentId={gaps.baseline?.document_id ?? null}
                      ledger={ledger ?? []}
                    onCreateFinding={onCreateFinding}
                    templates={templates}
                    />
                  ))}
                </ul>
              )}
              {notApplicableWithheld > 0 && (
                <p className="mt-2 text-xs text-slateish-500">
                  {withheldLine(notApplicableWithheld)}
                </p>
              )}
            </details>
          )}
        </>
      )}

      <p className="mt-3 border-t border-ink-700 pt-2 text-xs font-medium text-slateish-300">{REVIEW_SENTENCE}</p>
    </section>
  );
}
