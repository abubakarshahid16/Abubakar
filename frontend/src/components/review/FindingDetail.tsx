/**
 * One finding, in full, with both citations and the engineer's two actions.
 *
 * THE RATIONALE IS SHOWN VERBATIM. It carries prefixes the engine put there
 * on purpose - "Paired by model; engineer must confirm", "compared at the
 * highest of the submitted range -3 to 55 C" - and a screen that summarised
 * them would delete exactly the part a reviewer needs to judge the pairing.
 *
 * BOTH CITATIONS OPEN THE DOCUMENT AT THE CITED PAGE. A finding that names a
 * page nobody can reach is a claim without evidence (§12: no finding without
 * both citations resolving), so the page is one click away on each side.
 */
import { useEffect, useState } from "react";

import { api, reviews as reviewsApi } from "../../api/client";
import type { DocumentRecord, ReviewFinding } from "../../types/api";
import { DocumentPreview } from "../DocumentPreview";
import {
  confidenceLabel, findingLabel, matchMethodLabel, matchMethodTone, orNothing,
  statusTone, whenLabel,
} from "./reviewFormat";

export interface FindingDetailProps {
  finding: ReviewFinding;
  documents: DocumentRecord[];
  /** Standard document id -> filename. An id is not a name. */
  standardNames?: Map<string, string>;
  onChanged: () => void;
}

type Action =
  | { kind: "idle" }
  | { kind: "working" }
  | { kind: "error"; message: string }
  | { kind: "rejected" };

export function FindingDetail(
  { finding, documents, standardNames, onChanged }: FindingDetailProps,
) {
  const [action, setAction] = useState<Action>({ kind: "idle" });
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState<{ doc: DocumentRecord; page: number | null } | null>(null);

  // THE CITED DOCUMENTS, FETCHED BY ID WHEN THEY ARE NOT ALREADY IN HAND.
  // A findings list carries document IDs, and the page's document list holds
  // the submittals plus whatever standards fitted in one page of results - so
  // the standard a finding cites is often missing from it. Rendering "not
  // readable" in that case states something untrue about the reader's access;
  // the honest thing is to go and get it, and to say "still loading" until
  // the answer is known.
  const [fetched, setFetched] = useState<Record<string, DocumentRecord | null>>({});
  const standardId = finding.standard_document_id ?? null;
  const submittalId = finding.document_id ?? null;

  useEffect(() => {
    for (const id of [standardId, submittalId]) {
      if (!id) continue;
      if (documents.some((d) => d.id === id)) continue;
      if (id in fetched) continue;
      setFetched((current) => ({ ...current, [id]: null }));
      void api.document(id).then((result) => {
        setFetched((current) => ({
          ...current, [id]: result.ok ? result.data : null,
        }));
      });
    }
  }, [standardId, submittalId, documents, fetched]);

  const find = (id: string | null) =>
    (id ? documents.find((d) => d.id === id) ?? fetched[id] ?? null : null);
  const standard = find(standardId);
  const submittal = find(submittalId);
  const canReject = Boolean(finding.requirement_id && finding.fact_id);

  async function confirm() {
    setAction({ kind: "working" });
    const result = await reviewsApi.confirm(finding.id);
    if (!result.ok) {
      // SHOWN AS THE API RETURNED IT, never retried silently: a refusal
      // under scope is a real answer and hiding it would leave the engineer
      // clicking a button that appears to do nothing.
      setAction({ kind: "error", message: result.error.message });
      return;
    }
    setAction({ kind: "idle" });
    onChanged();
  }

  async function reject() {
    if (!reason.trim()) {
      setAction({ kind: "error", message: "A reason is required to reject a pairing." });
      return;
    }
    setAction({ kind: "working" });
    const result = await reviewsApi.rejectPairing(finding.id, reason.trim());
    if (!result.ok) {
      setAction({ kind: "error", message: result.error.message });
      return;
    }
    setAction({ kind: "rejected" });
    onChanged();
  }

  return (
    <section aria-labelledby="finding-detail-title" className="space-y-4 rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-4">
      <header className="flex flex-wrap items-start gap-3">
        <div>
          <h3 id="finding-detail-title" className="text-lg font-semibold text-slateish-100">
            {standardNames?.get(finding.standard_document_id ?? "")
              ?? orNothing(finding.standard_document_id)}
            {finding.standard_clause ? ` · clause ${finding.standard_clause}` : ""}
          </h3>
          {finding.equipment_tag && (
            <p className="text-sm text-slateish-400">Equipment: {finding.equipment_tag}</p>
          )}
        </div>
        <span className={`ml-auto rounded-full border px-3 py-1 text-xs ${statusTone(finding.compliance_status)}`}>
          {findingLabel(finding)}
        </span>
      </header>

      {finding.confirmed_by && (
        <p className="rounded-[var(--radius-sm)] border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
          Confirmed by {finding.confirmed_by}
          {finding.confirmed_at ? ` on ${whenLabel(finding.confirmed_at)}` : ""}.
          A confirmed finding is not deleted when the review is re-run.
        </p>
      )}

      <div>
        <h4 className="text-xs uppercase tracking-wide text-slateish-400">Requirement</h4>
        <p className="mt-1 whitespace-pre-wrap text-sm text-slateish-200">
          {orNothing(finding.requirement_source_text) || orNothing(finding.requirement)}
        </p>
      </div>

      <div>
        <h4 className="text-xs uppercase tracking-wide text-slateish-400">Why this outcome</h4>
        <p className="mt-1 whitespace-pre-wrap text-sm text-slateish-200">
          {orNothing(finding.ai_rationale)}
        </p>
        <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slateish-400">
          {finding.match_method && (
            <span className={`rounded-full border px-2 py-0.5 ${matchMethodTone(finding.match_method)}`}>
              {matchMethodLabel(finding.match_method)}
            </span>
          )}
          {finding.confidence && <span>confidence {confidenceLabel(finding.confidence)}</span>}
          {finding.matched_phrase && <span>matched field: {finding.matched_phrase}</span>}
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <Citation
          title="Standard" document={standard}
          page={finding.standard_page ?? null}
          detail={finding.standard_clause ? `clause ${finding.standard_clause}` : null}
          fallbackName={standardNames?.get(finding.standard_document_id ?? "")}
          onOpen={(doc, page) => setOpen({ doc, page })}
        />
        <Citation
          title="Submittal" document={submittal}
          page={finding.contractor_page ?? null}
          detail={orNothing(finding.contractor_evidence_text) || null}
          onOpen={(doc, page) => setOpen({ doc, page })}
        />
      </div>

      {open && (
        <div className="rounded-[var(--radius-md)] border border-ink-700 bg-ink-900 p-3">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm text-slateish-300">
              {open.doc.filename}{open.page ? ` — page ${open.page}` : ""}
            </p>
            <button
              type="button" onClick={() => setOpen(null)}
              className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-1 text-xs text-slateish-300"
            >Close</button>
          </div>
          {/* A HEIGHT THE PAGE CAN ACTUALLY BE READ IN. `DocumentPreview`
              fills its parent, and inside this panel that came to about
              150px - enough to show a header and nothing a reviewer could
              check a clause against. */}
          <div className="h-[32rem]">
            <DocumentPreview doc={open.doc} page={open.page} />
          </div>
        </div>
      )}

      <div className="space-y-3 border-t border-ink-700 pt-3">
        <h4 className="text-xs uppercase tracking-wide text-slateish-400">Engineer actions</h4>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button" onClick={() => void confirm()}
            disabled={action.kind === "working" || Boolean(finding.confirmed_by)}
            className="rounded-[var(--radius-sm)] bg-signal-500 px-3 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50"
          >
            {finding.confirmed_by ? "Confirmed" : "Confirm this finding"}
          </button>
        </div>
        {canReject ? (
          <div className="space-y-2">
            <label className="block text-xs text-slateish-400" htmlFor="reject-reason">
              Reject this pairing — say why (required)
            </label>
            <textarea
              id="reject-reason" value={reason} rows={2}
              onChange={(event) => setReason(event.target.value)}
              placeholder="e.g. interpass temperature is a welding parameter, not the service temperature"
              className="w-full rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-slateish-100"
            />
            <button
              type="button" onClick={() => void reject()}
              disabled={action.kind === "working" || action.kind === "rejected"}
              className="rounded-[var(--radius-sm)] border border-rose-500/50 px-3 py-2 text-sm text-rose-200 disabled:opacity-50"
            >
              Reject pairing
            </button>
          </div>
        ) : (
          <p className="text-xs text-slateish-500">
            This finding records no pairing, so there is nothing to reject.
          </p>
        )}
        {action.kind === "rejected" && (
          <p className="rounded-[var(--radius-sm)] border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            Pairing rejected. This pairing will not be proposed again.
          </p>
        )}
        {action.kind === "error" && (
          <p role="alert" className="rounded-[var(--radius-sm)] border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {action.message}
          </p>
        )}
      </div>
    </section>
  );
}

function Citation({ title, document, page, detail, fallbackName, onOpen }: {
  title: string;
  document: DocumentRecord | null;
  page: number | null;
  detail: string | null;
  fallbackName?: string;
  onOpen: (doc: DocumentRecord, page: number | null) => void;
}) {
  return (
    <div className="rounded-[var(--radius-sm)] border border-ink-700 bg-ink-900 p-3">
      <h5 className="text-xs uppercase tracking-wide text-slateish-400">{title}</h5>
      <p className="mt-1 text-sm text-slateish-200">{document?.filename ?? fallbackName ?? ""}</p>
      {page ? <p className="text-xs text-slateish-400">page {page}</p> : null}
      {detail ? <p className="mt-1 text-xs text-slateish-400">{detail}</p> : null}
      {document ? (
        <button
          type="button" onClick={() => onOpen(document, page)}
          className="mt-2 rounded-[var(--radius-sm)] border border-ink-600 px-2 py-1 text-xs text-signal-300"
        >
          Open at page {page ?? 1}
        </button>
      ) : (
        <p className="mt-2 text-xs text-slateish-500">
          {/* NOT "unreadable". Whether this account may read it is a
              different statement from whether the record has arrived, and
              only one of them is known here. */}
          The cited document could not be opened from this screen.
        </p>
      )}
    </div>
  );
}
