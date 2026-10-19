/**
 * v2.1 landing (switch on): the pure rules behind the first page.
 *
 * - `landingRowsOf`: one row per contractor document (and per document a
 *   run names whose record is missing, so no run is dropped silently),
 *   newest activity first (L4).
 * - `rowChip`: the plain status chip with counts (L3). Built on the inbox's
 *   own state rules (`inboxStateOf`), so the two lists never disagree. An
 *   unknown count is never 0: the chip then says "Ready" alone.
 * - `allRunsOf`: every run, newest started first, for "All reviews (N)" (L5).
 * - `matchesName`: the search box (L4).
 */
import type { DocumentRecord, ReviewRunSummary } from "../../../../types/api";
import { groupRunsByDocument, runStatusLabel } from "../../reviewFormat";
import { type InboxState, type ReadyCounts, inboxStateOf } from "../../inbox/inboxState";

export interface LandingRow {
  documentId: string;
  filename: string;
  latest: ReviewRunSummary | null;
  /** Every run of this document, newest first (latest included). */
  runs: ReviewRunSummary[];
  state: InboxState;
  /** The newest moment anything happened to this document (ISO), or null. */
  activityAt: string | null;
}

function time(value: string | null | undefined): number | null {
  if (!value) return null;
  const t = Date.parse(value);
  return Number.isNaN(t) ? null : t;
}

/** The newest of the given moments, as given (ISO), or null. */
function newest(values: (string | null | undefined)[]): string | null {
  let best: string | null = null;
  let bestT = -Infinity;
  for (const v of values) {
    const t = time(v);
    if (t !== null && t > bestT) { best = v!; bestT = t; }
  }
  return best;
}

/** A run's newest activity: started, finished, final code recorded, or signed. */
export function runActivityAt(run: ReviewRunSummary): string | null {
  return newest([run.created_at, run.completed_at, run.decided_at, run.crs_issued_at]);
}

export function landingRowsOf(documents: DocumentRecord[], runs: ReviewRunSummary[]): LandingRow[] {
  const byId = new Map<string, LandingRow>();
  for (const doc of documents) {
    byId.set(doc.id, {
      documentId: doc.id, filename: doc.filename, latest: null, runs: [],
      state: inboxStateOf(undefined), activityAt: newest([doc.uploaded_at, doc.indexed_at]),
    });
  }
  for (const group of groupRunsByDocument(runs)) {
    const existing = byId.get(group.documentId);
    const all = [group.latest, ...group.earlier];
    byId.set(group.documentId, {
      documentId: group.documentId,
      filename: existing?.filename ?? group.latest.submittal_filename ?? "(unnamed document)",
      latest: group.latest,
      runs: all,
      state: inboxStateOf(group.latest),
      activityAt: newest([existing?.activityAt, ...all.map(runActivityAt)]),
    });
  }
  return [...byId.values()].sort(byActivity);
}

function byActivity(a: LandingRow, b: LandingRow): number {
  const ta = time(a.activityAt);
  const tb = time(b.activityAt);
  if (ta !== tb) {
    if (ta === null) return 1; // unknown dates last
    if (tb === null) return -1;
    return tb - ta;
  }
  return a.filename.localeCompare(b.filename);
}

/** The search box: file name contains the words typed, any case. */
export function matchesName(filename: string, query: string): boolean {
  const q = query.trim().toLowerCase();
  return q === "" || filename.toLowerCase().includes(q);
}

export type ChipTone = "attention" | "ready" | "done" | "moving" | "failed" | "quiet";

export interface Chip {
  text: string;
  tone: ChipTone;
}

/** L3: the status chip. Counts come from the server's per-run counts
 *  (`loadReadyCounts`); null (not read yet, or failed) renders no number. */
export function rowChip(state: InboxState, counts: ReadyCounts | null): Chip {
  switch (state.kind) {
    case "not_reviewed":
      return { text: "Not reviewed", tone: "quiet" };
    case "queued":
      return { text: "Waiting to start", tone: "moving" };
    case "running": {
      const where = state.step !== null && state.of !== null ? ` (step ${state.step} of ${state.of})` : "";
      return { text: `Running${where}`, tone: "moving" };
    }
    case "ready":
      if (!counts) return { text: "Ready", tone: "ready" };
      if (counts.needs_you > 0) {
        return { text: `${counts.needs_you.toLocaleString("en-US")} need${counts.needs_you === 1 ? "s" : ""} you`, tone: "attention" };
      }
      return { text: "Ready to sign", tone: "ready" };
    case "signed":
      return { text: "Signed", tone: "done" };
    case "failed":
      return { text: `Failed: ${state.reason || "no reason was recorded"}`, tone: "failed" };
    case "cancelled":
      return { text: "Cancelled", tone: "quiet" };
    case "other":
      return { text: runStatusLabel(state.status) || state.status, tone: "quiet" };
  }
}

/** The line beside a Ready chip: how many findings the server counted, said
 *  as findings (the sheet groups them into fewer comment lines). Nothing
 *  when not known. */
export function countsLine(state: InboxState, counts: ReadyCounts | null): string {
  if (state.kind !== "ready" || !counts) return "";
  const n = counts.findings;
  return `${n.toLocaleString("en-US")} finding${n === 1 ? "" : "s"} to decide`;
}

/** L5: every run with its file name, newest started first. */
export interface RunListItem {
  run: ReviewRunSummary;
  filename: string;
  activityAt: string | null;
}

export function allRunsOf(documents: DocumentRecord[], runs: ReviewRunSummary[]): RunListItem[] {
  const names = new Map(documents.map((d) => [d.id, d.filename]));
  return runs
    .map((run) => ({
      run,
      filename: names.get(run.submittal_document_id) ?? run.submittal_filename ?? "(unnamed document)",
      activityAt: runActivityAt(run),
    }))
    .sort((a, b) => {
      const ta = time(a.run.created_at);
      const tb = time(b.run.created_at);
      if (ta !== tb) {
        if (ta === null) return 1;
        if (tb === null) return -1;
        return tb - ta;
      }
      return b.run.review_run_id.localeCompare(a.run.review_run_id);
    });
}
