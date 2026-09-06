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
import { useId, useState } from "react";

import type { BaselineSelection, GapAnalysis, GapItem, GapItemStatus } from "../../types/analysis";

const REVIEW_SENTENCE = "Review and approval by a qualified engineer is required.";

const STATUS: Record<GapItemStatus, { icon: string; text: string; tone: string; caption: string | null }> = {
  met: {
    icon: "✓",
    text: "Met",
    tone: "text-signal-400",
    caption: "Positive matching evidence was found.",
  },
  possible_gap: {
    icon: "▲",
    text: "Possible gap",
    tone: "text-warn-500",
    caption: "Retrieval found nothing addressing this. That is not proof the documents say nothing.",
  },
  conflict: {
    icon: "✕",
    text: "Conflict",
    tone: "text-danger-500",
    caption: null,
  },
  insufficient_evidence: {
    icon: "?",
    text: "Insufficient evidence",
    tone: "text-slateish-400",
    caption: null,
  },
  not_applicable: {
    icon: "—",
    text: "Not applicable",
    tone: "text-slateish-500",
    caption: null,
  },
};

function StatusMark({ status }: { status: GapItemStatus }) {
  const s = STATUS[status];
  return (
    <span className={["text-[11px] font-semibold uppercase tracking-wider", s.tone].join(" ")}>
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
}: {
  n: number;
  evidenceId: string;
  onCite: (evidenceId: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onCite(evidenceId)}
      aria-label={`Show project evidence ${n}`}
      className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded bg-ink-700 px-1 align-baseline font-mono text-[11px] leading-none text-slateish-300 hover:bg-ink-600"
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
}: {
  item: GapItem;
  onCite: (evidenceId: string) => void;
  baselineIsStated: boolean;
}) {
  const s = STATUS[item.status];
  return (
    <li className="border-t border-ink-700/60 py-3 first:border-t-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-sm font-semibold text-slateish-200">{item.facet}</h4>
        <StatusMark status={item.status} />
      </div>

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

      <div className="mt-2 flex flex-wrap items-baseline gap-x-2 text-xs text-slateish-400">
        <span>Project evidence:</span>
        {item.project_citation_ids.length === 0 ? (
          <span className="text-slateish-500">none cited</span>
        ) : (
          item.project_citation_ids.map((id, i) => (
            <EvidenceChip key={id} n={i + 1} evidenceId={id} onCite={onCite} />
          ))
        )}
      </div>

      {item.note !== null && <p className="mt-2 text-sm text-slateish-300">{item.note}</p>}
      {s.caption !== null && <p className={["mt-1.5 text-xs", s.tone].join(" ")}>{s.caption}</p>}
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

  function submit(e: React.FormEvent) {
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
    <form onSubmit={submit} className="mt-3 space-y-3 rounded border border-ink-700 p-3">
      <p className="text-xs text-slateish-400">Nominate a baseline: a document (optionally a section), or state the requirement.</p>
      <div>
        <label htmlFor={selectId} className="block text-xs text-slateish-400">
          Baseline document
        </label>
        <select
          id={selectId}
          value={documentId}
          onChange={(e) => setDocumentId(e.target.value)}
          className="mt-1 w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-slateish-200"
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
            className="mt-1 w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-slateish-200"
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
          className="mt-1 w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-slateish-200 disabled:opacity-60"
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
        className="rounded border border-ink-500 px-3 py-1.5 text-sm text-slateish-200 hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-50"
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
}: {
  gaps: GapAnalysis;
  onNominateBaseline?: (b: BaselineSelection) => void;
  documents: { id: string; filename: string }[];
  onCite: (evidenceId: string) => void;
}) {
  const heading = (
    <h3 className="text-[11px] font-semibold uppercase tracking-wider text-slateish-300">
      Preliminary gap assessment
    </h3>
  );

  if (gaps.applicability === "not_applicable") {
    return (
      <section aria-label="Gap analysis" className="rounded-lg border border-ink-600 bg-ink-850 p-4">
        {heading}
        <p className="mt-2 text-sm text-slateish-500">
          Gap analysis is not applicable: the question contains no comparison or baseline.
        </p>
      </section>
    );
  }

  if (gaps.applicability === "insufficient_baseline") {
    return (
      <section aria-label="Gap analysis" className="rounded-lg border border-ink-600 bg-ink-850 p-4" aria-live="polite">
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

  return (
    <section aria-label="Gap analysis" className="rounded-lg border border-ink-600 bg-ink-850 p-4">
      {heading}
      <BaselineHeader baseline={gaps.baseline} documents={documents} />

      {gaps.items.length === 0 ? (
        <p className="mt-3 text-sm text-slateish-500">No gap items were produced for this baseline.</p>
      ) : (
        <ul className="mt-3">
          {gaps.items.map((it, i) => (
            <ItemRow key={`${it.facet}-${i}`} item={it} onCite={onCite} baselineIsStated={baselineIsStated} />
          ))}
        </ul>
      )}

      <p className="mt-3 border-t border-ink-700 pt-2 text-xs font-medium text-slateish-300">{REVIEW_SENTENCE}</p>
    </section>
  );
}
