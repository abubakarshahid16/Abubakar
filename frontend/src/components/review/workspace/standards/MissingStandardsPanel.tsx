/**
 * OWNER: builder C (v2.1 gap T1). "Upload missing standards": each standard
 * the document mentions that the library does not hold, with an Upload
 * button, then "Review again" so the next review can use what was added.
 *
 * THE EXISTING UPLOAD PATH, NOTHING NEW. A file goes up through
 * `uploadOne` (components/Uploader.tsx), shared with whoever the uploader's
 * disciplines say (#609, `api.uploadDisciplines`). Then:
 *  - an administrator's upload is marked "Company standard" with the
 *    existing `classification.setRoleBulk` (admin only on the server);
 *  - anyone else's upload is NOT marked from here (the role write is admin
 *    only), and per #620 a Company standard a non-administrator uploads
 *    waits for an administrator to confirm it before reviews use it. The
 *    screen says both in plain words, so "uploaded" never reads as "the
 *    next review will use it".
 * A file that is already in the library is never re-marked.
 *
 * v2.1 round 2:
 *  - when the list could not be checked (`known` false) the panel says so,
 *    never "No standards are missing";
 *  - after an administrator's upload it waits for the file to be read in
 *    (newReview's `waitUntilReadIn`): "Reading it in…", then "Ready, press
 *    Review again";
 *  - "Review again" is hidden from someone who is not an administrator
 *    (`isAdmin` false), with the reason; only an administrator can start one.
 */
import { useRef, useState } from "react";

import { api, auth, classification } from "../../../../api/client";
import { hasAdminCapability } from "../../../Shell";
import { uploadOne } from "../../../Uploader";
import { READ_IN_SLOW_MESSAGE, waitUntilReadIn } from "../newReview";

export interface MissingStandardsPanelProps {
  runId: string;
  documentId: string | null;
  missing: { id?: string; name: string }[];
  onReviewAgain: () => void;
  /** False when the list of missing standards could not be checked yet
   *  (absent: known). */
  known?: boolean;
  /** False: not an administrator, so "Review again" is not offered.
   *  Absent: not known, the button shows (the server still decides). */
  isAdmin?: boolean;
}

export const NOT_CHECKED_MESSAGE = "Could not check which standards are missing yet";
export const ADMIN_ONLY_REVIEW_MESSAGE = "Only an administrator can start a review.";
export const READING_IN_MESSAGE = "Reading it in…";
export const READ_IN_READY_MESSAGE = "Ready, press Review again.";
export const READ_IN_SLOW_STANDARD_MESSAGE =
  "Uploaded and marked, but it is taking longer than usual to be read in. Press Review again once it shows as ready on the Documents page.";

const COMPANY_STANDARD = "COMPANY_STANDARD";

export const ADMIN_UPLOADED_MESSAGE =
  "Uploaded and marked as a company standard. Press \"Review again\" once it has been read in, so the review can use it.";
export const NON_ADMIN_UPLOADED_MESSAGE =
  "Uploaded. Because you are not an administrator, an administrator has to mark it as a company standard and confirm it "
  + "before reviews use it. Until then the next review will still list it as missing.";
export const ALREADY_IN_LIBRARY_MESSAGE =
  "This file is already in the library, so nothing was changed. If it is not marked as a company standard, an "
  + "administrator can mark it on the Documents page.";
export const AWAITING_ACCESS_MESSAGE =
  "Uploaded, but an administrator has to give access to it before anyone can use it.";

type ItemState =
  | { kind: "idle" }
  | { kind: "uploading"; percent: number }
  | { kind: "reading" }
  | { kind: "done"; message: string }
  | { kind: "error"; message: string };

/** Who the upload is shared with (#609); none when sign-in is off. */
async function uploadDisciplines(): Promise<{ ok: true; disciplines: string[] } | { ok: false; message: string }> {
  const r = await api.uploadDisciplines();
  if (!r.ok) return { ok: false, message: "Could not find out who the upload may be shared with, so nothing was uploaded." };
  if (!r.data.required) return { ok: true, disciplines: [] };
  if (r.data.default.length === 0) {
    return {
      ok: false,
      message: "You are not in any discipline, so an upload would be visible to nobody. Ask an administrator to add you to one.",
    };
  }
  return { ok: true, disciplines: r.data.default };
}

/** Upload one standard and mark it, as far as the caller may. */
export async function uploadMissingStandard(
  file: File, onProgress: (percent: number) => void,
): Promise<{ ok: true; message: string; readIn?: string } | { ok: false; message: string }> {
  const who = await uploadDisciplines();
  if (!who.ok) return who;
  const uploaded = await uploadOne(file, who.disciplines, onProgress);
  if (uploaded.phase === "error") return { ok: false, message: `Not uploaded: ${uploaded.message}` };
  if (uploaded.phase !== "done") return { ok: false, message: "The upload did not finish." };
  if (uploaded.duplicateOf) return { ok: true, message: ALREADY_IN_LIBRARY_MESSAGE };
  if (uploaded.awaitingGrant) return { ok: true, message: AWAITING_ACCESS_MESSAGE };
  // Unknown is treated as "not an administrator": the softer promise.
  const me = await auth.me();
  const isAdmin = me.ok && hasAdminCapability(me.data);
  if (!isAdmin) return { ok: true, message: NON_ADMIN_UPLOADED_MESSAGE };
  const marked = await classification.setRoleBulk({ document_ids: [uploaded.documentId], document_role: COMPANY_STANDARD });
  const failed = marked.ok && Array.isArray(marked.data.failed) ? marked.data.failed : [];
  if (!marked.ok || failed.length > 0) {
    return {
      ok: false,
      message: "Uploaded, but it could not be marked as a company standard"
        + (marked.ok ? "." : `: ${marked.error.message}`) + " Mark it on the Documents page.",
    };
  }
  // Used by the next review once it is read in: the panel waits for that.
  return { ok: true, message: ADMIN_UPLOADED_MESSAGE, readIn: uploaded.documentId };
}

const BUTTON = "rounded-[var(--radius-sm)] border px-3 py-1 text-sm disabled:cursor-not-allowed disabled:opacity-60";

function MissingRow({ name }: { name: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<ItemState>({ kind: "idle" });
  const pick = async (file: File | undefined) => {
    if (!file) return;
    setState({ kind: "uploading", percent: 0 });
    const outcome = await uploadMissingStandard(file, (percent) => setState({ kind: "uploading", percent }));
    if (input.current) input.current.value = "";
    if (!outcome.ok) { setState({ kind: "error", message: outcome.message }); return; }
    if (!outcome.readIn) { setState({ kind: "done", message: outcome.message }); return; }
    setState({ kind: "reading" });
    const read = await waitUntilReadIn(outcome.readIn, {});
    if (read.ok) setState({ kind: "done", message: READ_IN_READY_MESSAGE });
    else setState({ kind: "error", message: read.message === READ_IN_SLOW_MESSAGE ? READ_IN_SLOW_STANDARD_MESSAGE : read.message });
  };
  return (
    <li data-testid="missing-standard" className="space-y-1 py-2">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-medium text-slateish-100">{name}</span>
        <input ref={input} type="file" accept=".pdf,application/pdf" className="sr-only" tabIndex={-1}
          aria-label={`File for ${name}`} onChange={(e) => void pick(e.target.files?.[0])} />
        <button type="button" disabled={state.kind === "uploading" || state.kind === "reading"} onClick={() => input.current?.click()}
          className={`${BUTTON} ml-auto border-ink-600 text-slateish-100`}>
          {state.kind === "uploading" ? `Uploading… ${state.percent}%` : `Upload ${name}`}
        </button>
      </div>
      {state.kind === "reading" && <p role="status" className="text-xs text-slateish-300">{READING_IN_MESSAGE}</p>}
      {state.kind === "done" && <p role="status" className="text-xs text-slateish-300">{state.message}</p>}
      {state.kind === "error" && <p role="alert" className="text-xs text-danger-500">{state.message}</p>}
    </li>
  );
}

export function MissingStandardsPanel({
  runId, documentId, missing, onReviewAgain, known = true, isAdmin,
}: MissingStandardsPanelProps) {
  return (
    <section aria-label="Missing standards" data-testid="ws-missing-standards" data-run={runId}
      className="space-y-2 rounded-[var(--radius-md)] border border-ink-700 bg-ink-900 p-3 text-sm text-slateish-300">
      <h3 className="font-semibold text-slateish-100">
        {missing.length === 0
          ? (known ? "No standards are missing" : NOT_CHECKED_MESSAGE)
          : `Standards the document mentions that are not in the library (${missing.length.toLocaleString()})`}
      </h3>
      {!known && missing.length > 0 && (
        <p data-testid="ws-missing-not-checked">The full list could not be checked yet, so there may be more.</p>
      )}
      {missing.length > 0 && (
        <>
          <p>
            These were not checked. Upload each one as a PDF. An administrator&apos;s upload is used by the next
            review; anyone else&apos;s waits until an administrator confirms it.
          </p>
          <ul className="divide-y divide-ink-700">
            {missing.map((m) => <MissingRow key={m.id ?? m.name} name={m.name} />)}
          </ul>
        </>
      )}
      <div className="flex flex-wrap items-center gap-3 pt-1">
        {isAdmin === false ? (
          <span data-testid="ws-missing-admin-only" className="text-xs text-slateish-400">{ADMIN_ONLY_REVIEW_MESSAGE}</span>
        ) : (
          <>
            <button type="button" onClick={onReviewAgain} disabled={!documentId}
              className={`${BUTTON} border-ink-600 text-slateish-100`}>
              Review again
            </button>
            <span className="text-xs text-slateish-400">
              {documentId
                ? "Runs a fresh review of this document with the standards the library holds now."
                : "This review does not say which document it was, so it cannot be run again from here."}
            </span>
          </>
        )}
      </div>
    </section>
  );
}
