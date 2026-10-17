/** Owner order 2f: the engineer's internal notes, collapsed, fetched when
 *  opened. Moved verbatim from `ReviewRunsView.tsx` (#967 PR 3). */
import { useState } from "react";

import { reviews as reviewsApi } from "../../../api/client";
import type { CrsReviewNote } from "../../../types/api";

/** Owner order section 3: the engineer's internal notes on screen,
 *  collapsed. Fetched when opened - the same notes the internal CRS copy
 *  carries on its "Review notes" sheet, from the same builder. */
export function ReviewNotes({ runId }: { runId: string }) {
  const [notes, setNotes] = useState<CrsReviewNote[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <details className="text-sm" data-testid="review-notes"
      onToggle={(event) => {
        if (!(event.currentTarget as HTMLDetailsElement).open || notes !== null) return;
        void reviewsApi.previewCrs(runId).then((r) => {
          if (!r.ok) { setError(r.error.message); return; }
          setNotes(r.data.review_notes ?? []);
        });
      }}>
      <summary className="cursor-pointer text-slateish-200">Review notes - internal</summary>
      {error && <p role="alert" className="mt-1 text-xs text-danger-500">{error}</p>}
      {notes === null && !error && <p className="mt-1 text-xs text-slateish-400">Loading…</p>}
      {notes !== null && notes.length === 0 && (
        <p className="mt-1 text-xs text-slateish-400">No internal notes for this run.</p>
      )}
      {notes !== null && notes.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-slateish-300">
          {notes.map((n, i) => (
            <li key={i}>
              <span className="font-medium text-slateish-200">{n.note}</span>
              {n.standard ? ` - ${n.standard}` : ""}
              {n.count != null ? ` (${n.count})` : ""}
              {n.detail ? `: ${n.detail}` : ""}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
