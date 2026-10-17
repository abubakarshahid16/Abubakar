/**
 * AI Submittal Review: one run as a sheet to answer (#967 PR 2, Stage D).
 *
 * The owner's design in one line: a proofreader for datasheets. The
 * datasheet on the left; on the right one plain card per point, two buttons
 * each; one headline sentence and a ring of progress; a final decision; one
 * Send button. No dashboards, no step strips, no counters of counters.
 *
 * NOTHING HERE DECIDES. Each answer is the issue gate's own recorded
 * decision, the code is the existing code decision, and Send is the existing
 * issue route - which the server still refuses while anything is open. The
 * technical panels are kept, unchanged, behind "Behind the scenes" - each
 * a route of its own (`/review/<run>/<panel>`, #967 PR 3).
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { api, reviews as reviewsApi } from "../api/client";
import type { CrsIssueGate, DocumentRecord, ReviewFinding, ReviewRunSummary } from "../types/api";
import { downloadCrs } from "../components/review/downloadCrs";
import { progressLine, runStatusLabel } from "../components/review/reviewFormat";
import { DecisionCard } from "../components/review/sheet/DecisionCard";
import { DocumentPane, type PaneView } from "../components/review/sheet/DocumentPane";
import { ProgressRing } from "../components/review/sheet/ProgressRing";
import { SheetCard } from "../components/review/sheet/SheetCard";
import { type SheetCard as Card, buildCards, headline, passedCount, progress } from "../components/review/sheet/sheetCards";
import { useSheetKeys } from "../components/review/sheet/useSheetKeys";
import { BehindTheScenes, PANEL_TITLES, type StandardsState } from "../components/review/panels/BehindTheScenes";
import { ReviewJobControl } from "../components/review/panels/ReviewJobControl";
import { RunIncompleteNotes } from "../components/review/panels/RunIncompleteNotes";
import { RunReviewControl } from "../components/review/panels/RunReviewControl";

type Load = { kind: "loading" } | { kind: "ready" } | { kind: "error"; message: string };

export function ReviewSheetView({ runId, panel, onBack, onOpenPanel, onOpenRun, onOpenStandards, isAdmin = true }: {
  runId: string;
  /** A behind-the-scenes page (`routing.PANELS.review`), or the sheet itself. */
  panel?: string;
  onBack: () => void;
  onOpenPanel: (panel?: string) => void;
  /** A new run was started for this document: open it. */
  onOpenRun: (runId: string) => void;
  onOpenStandards?: () => void;
  isAdmin?: boolean;
}) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [run, setRun] = useState<ReviewRunSummary | null>(null);
  const [findings, setFindings] = useState<ReviewFinding[]>([]);
  const [gate, setGate] = useState<CrsIssueGate | null>(null);
  // A FAILED LIST IS NOT AN EMPTY ONE (audit 2026-09-30): the standards page
  // says the list could not be loaded, never "none were selected".
  const [standardsState, setStandardsState] = useState<StandardsState>({ standards: null, missing: [], error: null });
  const standards = standardsState.standards ?? [];
  const [submittal, setSubmittal] = useState<DocumentRecord | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [view, setView] = useState<PaneView>({ page: null, rule: null });
  // #791: the status a count in the review steps was clicked for.
  const [focusStatus, setFocusStatus] = useState<string | null>(null);
  const [send, setSend] = useState<{ kind: "idle" | "sending" | "sent" } | { kind: "error"; message: string }>({ kind: "idle" });

  const refresh = useCallback(async () => {
    const [runs, listed, gated, stds] = await Promise.all([
      reviewsApi.reviewRuns(), reviewsApi.list({ review_run_id: runId }),
      reviewsApi.crsIssueGate(runId), reviewsApi.reviewRunStandards(runId),
    ]);
    if (!runs.ok) { setLoad({ kind: "error", message: runs.error.message }); return null; }
    const found = runs.data.runs.find((r) => r.review_run_id === runId) ?? null;
    if (!found) { setLoad({ kind: "error", message: "This review run could not be found." }); return null; }
    if (!listed.ok) { setLoad({ kind: "error", message: listed.error.message }); return null; }
    setRun(found);
    setFindings(listed.data.findings);
    setGate(gated.ok ? gated.data : null);
    setStandardsState(stds.ok
      ? { standards: stds.data.standards, missing: stds.data.missing_references ?? [], error: null }
      : { standards: null, missing: [], error: stds.error.message });
    setLoad({ kind: "ready" });
    return { run: found, findings: listed.data.findings };
  }, [runId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const submittalId = run?.submittal_document_id ?? null;
  useEffect(() => {
    if (!submittalId) return;
    void api.document(submittalId).then((r) => setSubmittal(r.ok ? r.data : null));
  }, [submittalId]);

  const active = run?.status === "queued" || run?.status === "running";
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => { void refresh(); }, 3000);
    return () => clearInterval(timer);
  }, [active, refresh]);

  const cards = useMemo(() => buildCards(findings), [findings]);
  const selected = cards.find((c) => c.key === selectedKey)
    ?? cards.find((c) => c.state === "open") ?? null;
  const standardNames = useMemo(() => new Map(
    standards.filter((s) => s.filename).map((s) => [s.standard_document_id, s.filename as string])), [standards]);

  function select(card: Card | null, page?: number) {
    setSelectedKey(card?.key ?? null);
    setView({ page: page ?? card?.page ?? view.page, rule: null });
  }

  async function answered() {
    const before = selected?.key;
    const next = await refresh();
    if (!next) return;
    const fresh = buildCards(next.findings);
    const at = fresh.findIndex((c) => c.key === before);
    const after = [...fresh.slice(at + 1), ...fresh.slice(0, Math.max(at, 0))].find((c) => c.state === "open");
    select(after ?? fresh[at] ?? null);
  }

  useSheetKeys(cards, selected, select);

  if (panel && run) {
    return (
      <main className="mx-auto w-full max-w-7xl" aria-label={PANEL_TITLES[panel] ?? "Behind the scenes"}>
        <BehindTheScenes
          panel={panel} run={run} findings={findings} documents={submittal ? [submittal] : []}
          standardsState={standardsState} focusStatus={focusStatus}
          onOpenPanel={(next) => { if (!next) setFocusStatus(null); onOpenPanel(next); }}
          onFocusStatus={setFocusStatus}
          onStandardsChanged={(changed, missing) => setStandardsState({ standards: changed, missing, error: null })}
          onChanged={() => void refresh()}
        />
      </main>
    );
  }

  const done = progress(cards);
  const allAnswered = done.answered === done.total;
  const finalCode = run?.engineer_final_code ?? null;
  const canSend = allAnswered && Boolean(finalCode) && Boolean(gate?.issuable) && send.kind !== "sending";

  async function sendToContractor() {
    setSend({ kind: "sending" });
    const message = await downloadCrs(runId, "issue");
    if (message) { setSend({ kind: "error", message }); return; }
    setSend({ kind: "sent" });
    void refresh();
  }

  return (
    <main className="mx-auto w-full max-w-7xl space-y-5" aria-labelledby="sheet-title">
      <header className="space-y-3">
        <button type="button" onClick={onBack} className="text-sm text-signal-300 underline-offset-2 hover:underline">
          ← Documents from contractors
        </button>
        <div className="flex flex-wrap items-center gap-4">
          <div className="w-full min-w-0 sm:w-auto sm:flex-1">
            <h1 id="sheet-title" className="break-words text-2xl font-semibold text-slateish-100 sm:truncate">
              {run?.submittal_filename ?? "Review"}
            </h1>
            {load.kind === "ready" && run && !active && run.status !== "failed" && (
              <p className="mt-1 text-slateish-300" data-testid="sheet-headline">{headline(cards, gate, finalCode)}</p>
            )}
          </div>
          {cards.length > 0 && <ProgressRing answered={done.answered} total={done.total} />}
          <button type="button" onClick={() => void sendToContractor()} disabled={!canSend}
            className="rounded-[var(--radius-sm)] bg-signal-500 px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50">
            {send.kind === "sending" ? "Sending…" : "Send comments to contractor"}
          </button>
        </div>
        {run && <RunIncompleteNotes run={run} />}
        {send.kind === "sent" && <p role="status" className="text-sm text-signal-300">Sent. The issued copy was downloaded and kept on record.</p>}
        {send.kind === "error" && (
          <p role="alert" className="rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-sm text-danger-500">{send.message}</p>
        )}
      </header>

      {load.kind === "loading" && <p className="text-slateish-300">Loading the review…</p>}
      {load.kind === "error" && (
        <p role="alert" className="rounded-[var(--radius-md)] border border-danger-500/40 bg-danger-500/10 px-4 py-3 text-danger-500">{load.message}</p>
      )}
      {run && active && (
        <div className="space-y-1">
          <p aria-live="polite" className="text-slateish-300" data-testid="review-progress">
            {run.status === "queued" ? "Waiting to start"
              : run.job ? progressLine(run.job.progress_done, run.job.progress_total, run.job.progress_label) : runStatusLabel(run.status)}
            {run.job?.cancel_requested ? " · cancellation requested, stopping at the next step" : ""}
          </p>
          <ReviewJobControl run={run} onChanged={() => void refresh()} />
        </div>
      )}
      {run?.status === "failed" && (
        <p role="alert" className="text-danger-500">This check failed{run.failure_reason ? `: ${run.failure_reason}` : "."}</p>
      )}

      {load.kind === "ready" && run && !active && run.status !== "failed" && (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_26rem]">
          <DocumentPane
            submittal={submittal} cards={cards} selected={selected}
            view={{ ...view, page: view.page ?? selected?.page ?? null }}
            onPage={(page) => {
              const on = cards.filter((c) => c.pages.includes(page));
              const first = on.find((c) => c.state === "open") ?? on[0];
              if (first) select(first, page); else setView({ page, rule: null });
            }}
            onSelectCard={(card) => select(card, view.page ?? undefined)}
            onCloseRule={() => setView((v) => ({ ...v, rule: null }))}
          />
          <div className="space-y-3">
            {cards.map((card) => (
              <SheetCard
                key={card.key} card={card} runId={runId} selected={card.key === selected?.key}
                standardNames={standardNames} onSelect={() => select(card)}
                onOpenRule={(finding) => setView((v) => ({ ...v, rule: finding }))}
                onAnswered={() => void answered()}
              />
            ))}
            {cards.length === 0 && <p className="text-sm text-slateish-300">Nothing on this datasheet needs your answer.</p>}
            {(allAnswered || finalCode) && <DecisionCard key={`${run.review_run_id}-${finalCode ?? ""}`} run={run} onDecided={() => void refresh()} />}
            <p className="text-sm text-slateish-400">
              {passedCount(findings)} passed quietly ·{" "}
              <button type="button" onClick={() => onOpenPanel("findings")} className="text-signal-300 underline-offset-2 hover:underline">see all</button>
            </p>
            <p className="text-sm text-slateish-400">
              Behind the scenes:{" "}
              <button type="button" onClick={() => onOpenPanel("steps")} className="text-signal-300 underline-offset-2 hover:underline">how we checked this document</button>
              {" · "}
              <button type="button" onClick={() => onOpenPanel("standards")} className="text-signal-300 underline-offset-2 hover:underline">
                the rule books used ({standards.filter((s) => s.included).length} of {standards.length})
              </button>
              {" · "}
              <button type="button" onClick={() => onOpenPanel("numbers")} className="text-signal-300 underline-offset-2 hover:underline">AI numbers</button>
              {" · "}
              <button type="button" onClick={() => onOpenPanel("crs")} className="text-signal-300 underline-offset-2 hover:underline">the CRS</button>
            </p>
            {submittalId && !active && (
              <RunReviewControl
                key={submittalId} submittalId={submittalId} isAdmin={isAdmin} label="Check it again"
                onStarted={onOpenRun} onOpenStandards={onOpenStandards} onReread={async () => { await refresh(); }}
              />
            )}
          </div>
        </div>
      )}
    </main>
  );
}
