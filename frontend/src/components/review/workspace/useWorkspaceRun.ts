/**
 * OWNER: builder A. The run's data for the workspace.
 *
 * The same reads as CrsSheetView's `useRunData` (reviewRun, list,
 * reviewRunStandards, reviewRunSummary, document), plus the submittal's
 * readiness (`reviewsApi.readiness`) for the unread pages list. Only the
 * newest load may paint (a slow answer for a run the reader left, or a poll
 * overtaken by the next one, never replaces newer data). Polls every 3 s
 * while the run is queued or running. Rows are built with `buildCrsRows`,
 * exactly as the comment sheet builds them.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, reviews as reviewsApi } from "../../../api/client";
import type { DocumentRecord, ReviewFinding, ReviewReadiness, ReviewRunSummary, ReviewRunTierSummary } from "../../../types/api";
import { buildCrsRows } from "../crs/crsRows";
import { runFactsOf, serverTiersOf } from "../crs/tiers";
import type { StandardsState, WorkspaceLoad, WorkspaceRunData } from "./contract";

export const WORKSPACE_POLL_MS = 3000;

export function useWorkspaceRun(runId: string): WorkspaceRunData {
  const [load, setLoad] = useState<WorkspaceLoad>({ kind: "loading" });
  const [run, setRun] = useState<ReviewRunSummary | null>(null);
  const [findings, setFindings] = useState<ReviewFinding[]>([]);
  const [standardsState, setStandardsState] = useState<StandardsState>({ standards: null, missing: [], error: null });
  const [submittal, setSubmittal] = useState<DocumentRecord | null>(null);
  const [summary, setSummary] = useState<ReviewRunTierSummary | null>(null);
  const [readiness, setReadiness] = useState<ReviewReadiness | null>(null);

  const latest = useRef(0);
  useEffect(() => () => { latest.current += 1; }, []);
  const refresh = useCallback(async () => {
    const mine = ++latest.current;
    const [runs, listed, stds, sum] = await Promise.all([
      reviewsApi.reviewRun(runId), reviewsApi.list({ review_run_id: runId }), reviewsApi.reviewRunStandards(runId),
      reviewsApi.reviewRunSummary(runId),
    ]);
    if (mine !== latest.current) return;
    if (!runs.ok) { setLoad({ kind: "error", message: runs.error.message }); return; }
    const found = runs.data;
    if (!found) { setLoad({ kind: "error", message: "This review run could not be found." }); return; }
    if (!listed.ok) { setLoad({ kind: "error", message: listed.error.message }); return; }
    setRun(found);
    setFindings(listed.data.findings);
    setSummary(sum.ok ? sum.data : null);
    setStandardsState(stds.ok
      ? { standards: stds.data.standards, missing: stds.data.missing_references ?? [], error: null }
      : { standards: null, missing: [], error: stds.error.message });
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

  return { load, run, findings, rows, standardsState, missingStandardIds, standardNames, submittal, summary, readiness, active, refresh };
}
