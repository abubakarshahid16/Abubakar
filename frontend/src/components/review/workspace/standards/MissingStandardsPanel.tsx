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
 */
import { useRef, useState } from "react";

import { api, auth, classification } from "../../../../api/client";
import { hasAdminCapability } from "../../../Shell";
import { uploadOne } from "../../../Uploader";

export interface MissingStandardsPanelProps {
  runId: string;
  documentId: string | null;
  missing: { id?: string; name: string }[];
  onReviewAgain: () => void;
}

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
): Promise<{ ok: true; message: string } | { ok: false; message: string }> {
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
  return { ok: true, message: ADMIN_UPLOADED_MESSAGE };
}

const BUTTON = "rounded-[var(--radius-sm)] border px-3 py-1 text-sm disabled:cursor-not-allowed disabled:opacity-60";

function MissingRow({ name }: { name: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<ItemState>({ kind: "idle" });
  const pick = async (file: File | undefined) => {
    if (!file) return;
    setState({ kind: "uploading", percent: 0 });
    const outcome = await uploadMissingStandard(file, (percent) => setState({ kind: "uploading", percent }));
    setState(outcome.ok ? { kind: "done", message: outcome.message } : { kind: "error", message: outcome.message });
    if (input.current) input.current.value = "";
  };
  return (
    <li data-testid="missing-standard" className="space-y-1 py-2">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-medium text-slateish-100">{name}</span>
        <input ref={input} type="file" accept=".pdf,application/pdf" className="sr-only" tabIndex={-1}
          aria-label={`File for ${name}`} onChange={(e) => void pick(e.target.files?.[0])} />
        <button type="button" disabled={state.kind === "uploading"} onClick={() => input.current?.click()}
          className={`${BUTTON} ml-auto border-ink-600 text-slateish-100`}>
          {state.kind === "uploading" ? `Uploading… ${state.percent}%` : `Upload ${name}`}
        </button>
      </div>
      {state.kind === "done" && <p role="status" className="text-xs text-slateish-300">{state.message}</p>}
      {state.kind === "error" && <p role="alert" className="text-xs text-danger-500">{state.message}</p>}
    </li>
  );
}

export function MissingStandardsPanel({ runId, documentId, missing, onReviewAgain }: MissingStandardsPanelProps) {
  return (
    <section aria-label="Missing standards" data-testid="ws-missing-standards" data-run={runId}
      className="space-y-2 rounded-[var(--radius-md)] border border-ink-700 bg-ink-900 p-3 text-sm text-slateish-300">
      <h3 className="font-semibold text-slateish-100">
        {missing.length === 0
          ? "No standards are missing"
          : `Standards the document mentions that are not in the library (${missing.length.toLocaleString()})`}
      </h3>
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
        <button type="button" onClick={onReviewAgain} disabled={!documentId}
          className={`${BUTTON} border-ink-600 text-slateish-100`}>
          Review again
        </button>
        <span className="text-xs text-slateish-400">
          {documentId
            ? "Runs a fresh review of this document with the standards the library holds now."
            : "This review does not say which document it was, so it cannot be run again from here."}
        </span>
      </div>
    </section>
  );
}
