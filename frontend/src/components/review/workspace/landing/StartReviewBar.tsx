/**
 * v2.1 L1: the "select bar" is back. A searchable list of every contractor
 * submittal and a "Start review" button that ALWAYS starts a fresh review
 * (never opens an old one). Before it starts it asks when the latest review
 * is signed, carries the engineer's final code, or the readiness check says
 * nothing changed since (`ReviewAgainButton`'s one confirm). The start
 * watches the run (`reviewAgain` -> `watchRun`), so the "ready" notice
 * appears wherever the reader goes (L6).
 */
import { useId, useMemo, useState } from "react";

import type { DocumentRecord, ReviewRunSummary } from "../../../../types/api";
import { truncationNote } from "../../reviewFormat";
import { ReviewAgainButton } from "../ReviewAgainButton";
import { matchesName } from "./landingRows";

export function StartReviewBar({ documents, submittalsTotal, runs, onStarted }: {
  /** Every CONTRACTOR_SUBMITTAL document the page loaded. */
  documents: DocumentRecord[];
  submittalsTotal: number | null;
  runs: ReviewRunSummary[];
  onStarted: (runId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState("");
  const selectId = useId();
  const sorted = useMemo(
    () => [...documents].sort((a, b) => a.filename.localeCompare(b.filename)),
    [documents],
  );
  const shown = sorted.filter((d) => matchesName(d.filename, query) || d.id === chosen);
  const chosenDoc = documents.find((d) => d.id === chosen) ?? null;
  const boundary = truncationNote(documents.length, submittalsTotal, "contractor submittals");

  return (
    <div className="space-y-2" data-testid="start-review-bar">
      <label htmlFor={selectId} className="block text-sm font-medium text-slateish-200">Choose a submittal</label>
      {documents.length === 0 ? (
        <p className="text-sm text-slateish-300">There are no contractor submittals to choose from yet. Drop a file below instead.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type to find a file"
            aria-label="Find a submittal by file name"
            className="min-w-[12rem] flex-1 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-3 py-1.5 text-sm text-slateish-100"
          />
          <select
            id={selectId}
            value={chosen}
            onChange={(e) => setChosen(e.target.value)}
            className="min-w-[12rem] flex-1 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-3 py-1.5 text-sm text-slateish-100"
          >
            <option value="">
              {shown.length === 0 ? "No file name matches" : `Choose one of ${shown.length.toLocaleString("en-US")}`}
            </option>
            {shown.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
          </select>
          <ReviewAgainButton
            documentId={chosen}
            filename={chosenDoc?.filename ?? null}
            runs={runs}
            label="Start review"
            primary
            disabled={!chosen}
            onStarted={onStarted}
          />
        </div>
      )}
      <p className="text-xs text-slateish-400">Start review always starts a fresh review. Earlier reviews stay as they are.</p>
      {boundary && <p className="text-xs text-slateish-400">{boundary}</p>}
    </div>
  );
}
