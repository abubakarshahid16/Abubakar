/**
 * OWNER: builder A. The run's data for the workspace.
 *
 * The same reads as CrsSheetView's `useRunData` (reviewRun, list,
 * reviewRunStandards, reviewRunSummary, document), plus the submittal's
 * readiness (`reviewsApi.readiness`) for the unread pages list. Only the
 * newest load may paint (a slow answer for a run the reader left, or a poll
 * overtaken by the next one, never replaces newer data). Polls every 3 s
 * while the run is queued or running. Once the run has shown, a read that
 * fails keeps the last good data (`refreshError` says so) instead of
 * replacing the screen with an error. Rows are built with `buildCrsRows`,
 * exactly as the comment sheet builds them.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, reviews as reviewsApi } from "../../../api/client";
import type { DocumentRecord, ReviewFinding, ReviewReadiness, ReviewRunSummary, ReviewRunTierSummary } from "../../../types/api";
import { buildCrsRows } from "../crs/crsRows";
import { runFactsOf, serverTiersOf } from "../crs/tiers";
import type { StandardsState, WorkspaceLoad, WorkspaceRunData } from "./contract";
import { plainErrorText } from "./plainError";

export const WORKSPACE_POLL_MS = 3000;

/** Said under the bar when a re-read failed but the last good answer is
 *  still on screen. */
export const COULD_NOT_REFRESH = "Could not refresh just now; showing what was last read. It will try again.";

/** v2.1 (N2/W1): the plain words when the review is not there. */
export const REVIEW_NOT_FOUND = "This review could not be found. It may have been removed, or the link may be wrong.";
/** What could not be done, said before the plain reason (plainError). */
export const COULD_NOT_OPEN = "Could not open this review.";
export const COULD_NOT_READ_STANDARDS = "Could not read the list of standards for this review.";

/** The workspace's data, plus `refreshError`: set when a later read failed
 *  and the screen kept the last good answer (null otherwise). */
export interface WorkspaceRunState extends WorkspaceRunData {
  refreshError: string | null;
}

export function useWorkspaceRun(runId: string): WorkspaceRunState {
  const [load, setLoad] = useState<WorkspaceLoad>({ kind: "loading" });
  const [refreshError, setRefreshError] = useState<string | null>(null);
  // Whether this run has painted once: after that a failed read keeps the
  // screen as it was and only says it could not refresh.
  const loadedOnce = useRef(false);
  const [run, setRun] = useState<ReviewRunSummary | null>(null);
  const [findings, setFindings] = useState<ReviewFinding[]>([]);
  const [standardsState, setStandardsState] = useState<StandardsState>({ standards: null, missing: [], error: null });
  const [submittal, setSubmittal] = useState<DocumentRecord | null>(null);
  const [summary, setSummary] = useState<ReviewRunTierSummary | null>(null);
  const [readiness, setReadiness] = useState<ReviewReadiness | null>(null);

  const latest = useRef(0);
  useEffect(() => () => { latest.current += 1; }, []);
  useEffect(() => { loadedOnce.current = false; }, [runId]);
  const refresh = useCallback(async () => {
    const mine = ++latest.current;
    const [runs, listed, stds, sum] = await Promise.all([
      reviewsApi.reviewRun(runId), reviewsApi.list({ review_run_id: runId }), reviewsApi.reviewRunStandards(runId),
      reviewsApi.reviewRunSummary(runId),
    ]);
    if (mine !== latest.current) return;
    if (!runs.ok || !listed.ok) {
      // v2.1 (N2): a plain sentence first; the server's words only as a
      // detail after it, never alone.
      const message = plainErrorText(COULD_NOT_OPEN, !runs.ok ? runs : !listed.ok ? listed : null);
      // One failed poll never replaces a screen that was already showing
      // the run: keep the last good data and say it could not refresh.
      if (loadedOnce.current) setRefreshError(COULD_NOT_REFRESH);
      else setLoad({ kind: "error", message });
      return;
    }
    const found = runs.data;
    if (!found) { setLoad({ kind: "error", message: REVIEW_NOT_FOUND }); return; }
    loadedOnce.current = true;
    setRefreshError(null);
    setRun(found);
    setFindings(listed.data.findings);
    setSummary(sum.ok ? sum.data : null);
    setStandardsState(stds.ok
      ? { standards: stds.data.standards, missing: stds.data.missing_references ?? [], error: null }
      : { standards: null, missing: [], error: plainErrorText(COULD_NOT_READ_STANDARDS, stds) });
    setLoad({ kind: "ready" });
    // Readiness (unread pages, missing standards) is read after the run,
    // because it is keyed by the run's submittal. A failure leaves it null
    // ("not known"), never an empty list.
    const submittalId = found.submittal_document_id;
    if (!submittalId) { setReadiness(null); return; }
    const ready = await reviewsApi.readiness(submittalId);
    if (mine !== latest.current) return;
    setReadiness(ready.ok ? ready.data : null);
  }, [runId]);
  useEffect(() => { void refresh(); }, [refresh]);

  const submittalId = run?.submittal_document_id ?? null;
  useEffect(() => {
    if (!submittalId) return;
    let current = true;
    void api.document(submittalId).then((r) => { if (current) setSubmittal(r.ok ? r.data : null); });
    return () => { current = false; };
  }, [submittalId]);

  const active = run?.status === "queued" || run?.status === "running";
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => { void refresh(); }, WORKSPACE_POLL_MS);
    return () => clearInterval(timer);
  }, [active, refresh]);

  const standardNames = useMemo(() => new Map(
    (standardsState.standards ?? []).filter((s) => s.filename).map((s) => [s.standard_document_id, s.filename as string])),
  [standardsState.standards]);
  // Not known (null) while the standards read failed or has not answered.
  const missingStandardIds = useMemo(() => (standardsState.error !== null || standardsState.standards === null
    ? null : standardsState.missing.map((m) => m.identifier)), [standardsState]);
  const facts = useMemo(() => runFactsOf(run, standardsState.standards, standardsState.missing), [run, standardsState]);
  const server = useMemo(() => (summary ? serverTiersOf(summary.rows) : null), [summary]);
  const rows = useMemo(() => buildCrsRows(findings, facts, standardNames, server), [findings, facts, standardNames, server]);

  return {
    load, run, findings, rows, standardsState, missingStandardIds, standardNames, submittal, summary, readiness, active, refresh,
    refreshError,
  };
}
