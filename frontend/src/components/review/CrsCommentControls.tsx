/**
 * What happens to a CRS comment AFTER it is issued (2026-09-29, industry CRS
 * practice): the contractor replies with a response code, the reviewer - and
 * only the reviewer - closes it, and every step is on record.
 *
 * Shown only on a NUMBERED row: a comment an engineer has made theirs carries
 * a permanent "CRS-<submittal no>-001". An unnumbered draft is not a comment
 * yet, so it has nothing to reply to or close.
 *
 * Every action goes to the server, which records WHO from the session - this
 * screen never sends a name. After any change the sheet is re-read from the
 * server rather than patched here, so the table always shows what the file
 * will say.
 */
import { useState } from "react";

import { reviews as reviewsApi } from "../../api/client";
import type {
  CrsCommentEvent, CrsPreviewRow, CrsReplyImport, CrsResponseCode,
} from "../../types/api";

const RESPONSE_CODES: CrsResponseCode[] = [
  "Accepted", "Accepted with comment", "Rejected", "Clarification needed",
];

const button =
  "rounded-[var(--radius-sm)] border border-ink-600 px-2 py-0.5 text-[11px] text-slateish-200 disabled:opacity-50";
const errorText = "text-[11px] text-rose-300";

/** Import the contractor's returned sheet (.xlsx). */
export function CrsReplyImportControl(
  { runId, onChanged }: { runId: string; onChanged: () => void },
) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CrsReplyImport | null>(null);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    const r = await reviewsApi.importCrsReply(runId, file);
    setBusy(false);
    if (!r.ok) {
      setError(r.error.message);
      return;
    }
    setResult(r.data);
    onChanged();
  }

  return (
    <div className="space-y-1 text-xs">
      <label className="inline-flex cursor-pointer items-center gap-2 text-slateish-200">
        <span className={button}>{busy ? "Importing…" : "Import contractor reply (.xlsx)"}</span>
        <input
          type="file" accept=".xlsx" className="sr-only" disabled={busy}
          aria-label="Import contractor reply"
          onChange={(e) => { void onFile(e.target.files?.[0]); e.target.value = ""; }}
        />
      </label>
      {error && <p role="alert" className={errorText}>{error}</p>}
      {result && (
        // WITH ITS DENOMINATOR: every row that carried an Item No is counted
        // in exactly one of these.
        <p role="status" className="text-slateish-300">
          {result.rows_read} row(s) read: {result.updated} reply(ies) stored
          {result.updated_without_code > 0 && `, ${result.updated_without_code} stored with no response code stated`}
          {result.no_response > 0 && `, ${result.no_response} not answered`}
          {result.unknown_number + result.other_submittal > 0
            && `, ${result.unknown_number + result.other_submittal} with a number that is not this submittal's comment`}
          {result.not_a_crs_number > 0 && `, ${result.not_a_crs_number} without a CRS number (skipped)`}.
          {" "}Statuses were not changed: only the reviewer closes a comment.
        </p>
      )}
    </div>
  );
}

/** The Contractor's Response cell: the reply, and "Record reply" for one
 *  that arrived by email or letter. */
export function CrsResponseCell(
  { runId, row, onChanged }: { runId: string; row: CrsPreviewRow; onChanged: () => void },
) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState<CrsResponseCode | "">("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = row.crs_ref ?? "";

  async function save() {
    setBusy(true);
    setError(null);
    const r = await reviewsApi.recordCrsResponse(runId, ref, code || null, text);
    setBusy(false);
    if (!r.ok) {
      setError(r.error.message);
      return;
    }
    setOpen(false);
    onChanged();
  }

  return (
    <div className="space-y-1">
      <p className="whitespace-pre-line text-slateish-200">{row.contractor_response}</p>
      {ref && !open && (
        <button type="button" className={button} onClick={() => setOpen(true)}>
          Record reply
        </button>
      )}
      {ref && open && (
        <div className="space-y-1">
          <select
            aria-label={`Response code for ${ref}`} value={code}
            onChange={(e) => setCode(e.target.value as CrsResponseCode | "")}
            className="w-full rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-1 py-0.5 text-[11px] text-slateish-100"
          >
            {/* NO CODE IS A REAL ANSWER, not a default for "Accepted". */}
            <option value="">No response code stated</option>
            {RESPONSE_CODES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <textarea
            aria-label={`Contractor's reply to ${ref}`} value={text} rows={2}
            onChange={(e) => setText(e.target.value)} maxLength={4000}
            className="w-full rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-1 py-0.5 text-[11px] text-slateish-100"
          />
          <div className="flex gap-1">
            <button type="button" className={button} disabled={busy || (!code && !text.trim())}
              onClick={() => void save()}>
              {busy ? "Saving…" : "Save reply"}
            </button>
            <button type="button" className={button} onClick={() => setOpen(false)}>Cancel</button>
          </div>
          {error && <p role="alert" className={errorText}>{error}</p>}
        </div>
      )}
    </div>
  );
}

/** The Final Resolution cell: Open/Closed, and Close / Reopen. */
export function CrsResolutionCell(
  { runId, row, onChanged }: { runId: string; row: CrsPreviewRow; onChanged: () => void },
) {
  const [closing, setClosing] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = row.crs_ref ?? "";
  const isClosed = row.final_resolution.startsWith("Closed");

  async function change(status: "Open" | "Closed") {
    setBusy(true);
    setError(null);
    const r = await reviewsApi.setCrsCommentStatus(runId, ref, status, note);
    setBusy(false);
    if (!r.ok) {
      setError(r.error.message);
      return;
    }
    setClosing(false);
    setNote("");
    onChanged();
  }

  return (
    <div className="space-y-1">
      <p className={isClosed ? "text-emerald-300" : "text-slateish-200"}>{row.final_resolution}</p>
      {ref && isClosed && (
        <button type="button" className={button} disabled={busy} onClick={() => void change("Open")}>
          Reopen
        </button>
      )}
      {ref && !isClosed && !closing && (
        <button type="button" className={button} onClick={() => setClosing(true)}>Close</button>
      )}
      {ref && !isClosed && closing && (
        <div className="space-y-1">
          <input
            aria-label={`Closing note for ${ref}`} value={note} maxLength={2000}
            placeholder="Closing note (optional)"
            onChange={(e) => setNote(e.target.value)}
            className="w-full rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-1 py-0.5 text-[11px] text-slateish-100"
          />
          <div className="flex gap-1">
            <button type="button" className={button} disabled={busy}
              onClick={() => void change("Closed")}>
              {busy ? "Closing…" : "Confirm close"}
            </button>
            <button type="button" className={button} onClick={() => setClosing(false)}>Cancel</button>
          </div>
        </div>
      )}
      {error && <p role="alert" className={errorText}>{error}</p>}
    </div>
  );
}

/** Item No, with the comment's history for a numbered row. */
export function CrsItemCell({ runId, row }: { runId: string; row: CrsPreviewRow }) {
  const [events, setEvents] = useState<CrsCommentEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ref = row.crs_ref ?? "";

  async function toggle() {
    if (events) {
      setEvents(null);
      return;
    }
    setError(null);
    const r = await reviewsApi.crsCommentHistory(runId, ref);
    if (!r.ok) {
      setError(r.error.message);
      return;
    }
    setEvents(r.data.events);
  }

  return (
    <div className="space-y-1">
      <span>{row.item_no}</span>
      {row.row_kind === "carried_forward" && (
        <p className="text-[10px] text-sky-300">carried forward</p>
      )}
      {ref && (
        <button type="button" className={button} aria-expanded={events !== null}
          onClick={() => void toggle()}>
          {events ? "Hide history" : "History"}
        </button>
      )}
      {error && <p role="alert" className={errorText}>{error}</p>}
      {events && (
        <ol className="space-y-0.5 text-left text-[10px] text-slateish-300">
          {events.map((e, i) => (
            <li key={i}>
              {e.at.slice(0, 16).replace("T", " ")} - {e.event}
              {e.detail ? ` (${e.detail})` : ""}{e.by ? ` - ${e.by}` : ""}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
