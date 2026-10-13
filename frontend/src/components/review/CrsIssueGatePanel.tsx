/**
 * PF5 (#885): what still stands between this run and its contractor copy,
 * and the engineer's way to close each item without waiting for any AI.
 *
 * WHAT IT REFUSES TO DO:
 *  - Decide without a reason. Every decision carries the engineer's own
 *    words; who and when are the server's (the signed-in caller, the clock).
 *  - Hide why issue is refused. Each blocker is printed as the server words
 *    it, and the list is re-read after every decision.
 *  - Count a page as read. An unread page is closed only by an engineer
 *    saying they checked it by eye.
 */
import { useCallback, useEffect, useState } from "react";

import { reviews as reviewsApi } from "../../api/client";
import type { ApiError, CrsIssueGate } from "../../types/api";

type Load =
  | { state: "loading" }
  | { state: "error"; error: ApiError }
  | { state: "ready"; gate: CrsIssueGate };

export function CrsIssueGatePanel({ runId, onChange }: { runId: string; onChange?: () => void }) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const result = await reviewsApi.crsIssueGate(runId);
      if (result.ok) setLoad({ state: "ready", gate: result.data });
      else setLoad({ state: "error", error: result.error });
    } catch {
      // never a silent blank: the panel says it could not check
      setLoad({ state: "error", error: { code: "internal", message: "Could not check what is still open." } });
    }
  }, [runId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const decide = async (key: string, call: (reason: string) => ReturnType<typeof reviewsApi.decideCrsPage>) => {
    const reason = (reasons[key] ?? "").trim();
    if (reason.length < 3) {
      setFailure("Write the reason for this decision first.");
      return;
    }
    setBusy(key);
    setFailure(null);
    const result = await call(reason);
    setBusy(null);
    if (!result.ok) {
      setFailure(result.error.message || "The decision was not recorded.");
      return;
    }
    setReasons((r) => ({ ...r, [key]: "" }));
    await refresh();
    onChange?.();
  };

  if (load.state === "loading") return <p className="text-xs text-slateish-400">Checking what is still open…</p>;
  if (load.state === "error") {
    return <p data-testid="issue-gate-error" className="text-xs text-slateish-400">{load.error.message}</p>;
  }
  const { gate } = load;
  const reasonBox = (key: string, label: string) => (
    <input
      aria-label={label} value={reasons[key] ?? ""}
      onChange={(e) => setReasons((r) => ({ ...r, [key]: e.target.value }))}
      className="min-w-0 flex-1 rounded-[var(--radius-sm)] border border-ink-600 bg-transparent px-2 py-1 text-xs"
      placeholder="Your reason"
    />
  );

  return (
    <section aria-labelledby={`issue-gate-${runId}`} className="flex flex-col gap-2 text-xs">
      <h4 id={`issue-gate-${runId}`} className="text-sm font-medium">
        {gate.issuable ? "Ready to issue to the contractor" : "Not ready to issue to the contractor"}
      </h4>
      {gate.blockers.length > 0 && (
        <ul data-testid="issue-blockers" className="list-disc pl-5 text-slateish-300">
          {gate.blockers.map((b) => <li key={b}>{b}</li>)}
        </ul>
      )}
      {failure && <p role="alert" className="text-red-400">{failure}</p>}
      {gate.unread_pages.map((p) => {
        const key = `page-${p.page}`;
        return (
          <div key={key} data-testid={key} className="flex flex-wrap items-center gap-2">
            <span>Page {p.page} was not read{p.reason ? ` (${p.reason})` : ""}.</span>
            {reasonBox(key, `Reason for page ${p.page}`)}
            <button type="button" disabled={busy === key}
                    onClick={() => void decide(key, (r) => reviewsApi.decideCrsPage(runId, p.page, r))}>
              I checked this page
            </button>
          </div>
        );
      })}
      {gate.open_findings.map((f) => {
        const key = `finding-${f.finding_id}`;
        return (
          <div key={key} data-testid={key} className="flex flex-wrap items-center gap-2">
            <span>Item {f.item} has no engineer's decision.</span>
            {reasonBox(key, `Reason for item ${f.item}`)}
            <button type="button" disabled={busy === key}
                    onClick={() => void decide(key, (r) => reviewsApi.decideCrsFinding(runId, f.finding_id, "accept", r))}>
              Accept
            </button>
            <button type="button" disabled={busy === key}
                    onClick={() => void decide(key, (r) => reviewsApi.decideCrsFinding(runId, f.finding_id, "reject", r))}>
              Reject
            </button>
          </div>
        );
      })}
    </section>
  );
}
