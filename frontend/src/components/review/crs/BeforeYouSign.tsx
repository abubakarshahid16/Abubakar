/**
 * Order 121 Part A: "Before you sign" on the comment sheet.
 *
 * The server refuses the contractor's copy until (1) an engineer records the
 * final code, (2) every unread page is closed with a reason and (3) every
 * item on the copy is decided. The sheet covered (3) through Save decisions
 * only; (1) and (2) could be done on the old card view's issue gate alone,
 * which listed every raw finding, one line and one reason box each.
 * This box closes all three on the sheet, in the sheet's words, with the
 * same routes the old panel used (no new endpoint):
 *  - the final code, the computer's proposal pre-selected and named as such;
 *  - one line per unread page, ticked with a short reason;
 *  - undecided items per COMMENT ROW, a click opening the row; items on the
 *    issued copy that are not rows on this sheet (a standard not cited, ...)
 *    are decided together with one reason.
 * Sign and export waits until the gate is clear, and says what is left.
 */
import { useState } from "react";

import { reviews as reviewsApi } from "../../../api/client";
import type { CrsIssueGate, ReviewRunSummary } from "../../../types/api";
import { REVIEW_CODES } from "../../../types/api";
import type { CrsRow } from "./crsRows";
import { type IssueGateState, MIN_SIGN_REASON, otherItemLines, plural, signLeft, splitOpenItems, unreadPagesLine } from "./issueGate";
import { unreadPageLine } from "./pageReasons";
import { type PlainError, plainError } from "../workspace/plainError";
import { PlainErrorLine } from "../workspace/PlainErrorLine";

const box = "space-y-2 rounded-[var(--radius-sm)] border p-3";
const input = "min-w-0 flex-1 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-2 py-1 text-sm text-slateish-100";
const button = "rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-sm text-slateish-100 disabled:opacity-50";
const link = "text-signal-300 underline-offset-2 hover:underline";

function Mark({ done }: { done: boolean }) {
  return <span aria-hidden="true">{done ? "✅" : "❌"}</span>;
}

export function FinalCode({ run, onChanged }: { run: ReviewRunSummary; onChanged: () => void }) {
  const codes: readonly string[] = run.review_codes?.length ? run.review_codes : REVIEW_CODES;
  const [code, setCode] = useState(run.recommended_code ?? "");
  const [why, setWhy] = useState("");
  const [state, setState] = useState<{ busy: boolean; error: PlainError | null }>({ busy: false, error: null });
  const differs = Boolean(run.recommended_code && code && code !== run.recommended_code);
  if (run.engineer_final_code) {
    return (
      <div className={`${box} border-ink-700`} data-testid="sign-code">
        <p className="text-sm text-slateish-100"><Mark done /> Final code recorded: {run.engineer_final_code}.</p>
      </div>
    );
  }
  async function record() {
    if (differs && !why.trim()) {
      setState({ busy: false, error: { words: "Say why your code differs from the computer's proposal.", detail: null } });
      return;
    }
    setState({ busy: true, error: null });
    const result = await reviewsApi.decideCode(run.review_run_id, code, why.trim() || null);
    if (!result.ok) { setState({ busy: false, error: plainError("The final code was not recorded.", result) }); return; }
    setState({ busy: false, error: null });
    onChanged();
  }
  return (
    <fieldset className={`${box} border-warn-500/40`} data-testid="sign-code">
      <legend className="px-1 text-sm text-slateish-100"><Mark done={false} /> Record the final code</legend>
      {codes.map((value) => (
        <label key={value} className="flex items-center gap-2 text-sm text-slateish-200">
          <input type="radio" name={`sign-code-${run.review_run_id}`} value={value} checked={code === value} onChange={() => setCode(value)} />
          {value}
          {value === run.recommended_code && <span className="text-xs text-slateish-400">(the computer's proposal)</span>}
        </label>
      ))}
      {differs && (
        <label className="block text-xs text-slateish-400">
          Why it differs from the computer's proposal (required)
          <textarea rows={2} value={why} onChange={(e) => setWhy(e.target.value)} className={`mt-1 w-full ${input}`} />
        </label>
      )}
      <button type="button" onClick={() => void record()} disabled={!code || state.busy} className={button}>
        {state.busy ? "Recording…" : "Record the final code"}
      </button>
      {state.error && <PlainErrorLine error={state.error} className="text-sm text-danger-500" testId="sign-code-error" />}
    </fieldset>
  );
}

function UnreadPages({ runId, gate, onDecided }: { runId: string; gate: CrsIssueGate; onDecided: () => Promise<void> }) {
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pages = gate.unread_pages;
  async function tick(page: number) {
    const reason = (reasons[page] ?? "").trim();
    if (reason.length < MIN_SIGN_REASON) { setError(`Write what you checked on page ${page} (${MIN_SIGN_REASON} characters at least).`); return; }
    setBusy(page);
    setError(null);
    const result = await reviewsApi.decideCrsPage(runId, page, reason);
    setBusy(null);
    if (!result.ok) { setError(result.error.message || "The tick was not recorded."); return; }
    setReasons((r) => ({ ...r, [page]: "" }));
    await onDecided();
  }
  const details = pages.filter((p) => p.reason);
  const line = unreadPagesLine(gate);
  return (
    <div className={`${box} ${pages.length ? "border-warn-500/40" : "border-ink-700"}`} data-testid="sign-pages">
      <p className="text-sm text-slateish-100">
        <Mark done={line.done} /> {line.text}
      </p>
      {pages.map((p) => (
        <div key={p.page} className="flex flex-wrap items-center gap-2 text-sm text-slateish-200" data-testid={`sign-page-${p.page}`}>
          <span>{unreadPageLine(p.page, p.reason)} Tick if you checked it yourself.</span>
          <input aria-label={`What you checked on page ${p.page}`} value={reasons[p.page] ?? ""} placeholder="What you checked"
            onChange={(e) => setReasons((r) => ({ ...r, [p.page]: e.target.value }))} className={input} />
          <button type="button" disabled={busy === p.page} onClick={() => void tick(p.page)} className={button}>
            I checked page {p.page}
          </button>
        </div>
      ))}
      {details.length > 0 && (
        <details className="text-xs text-slateish-400">
          <summary className="cursor-pointer">Technical details</summary>
          <ul className="mt-1 list-disc pl-5">
            {details.map((p) => <li key={p.page}>Page {p.page}: {p.reason}</li>)}
          </ul>
        </details>
      )}
      {error && <p role="alert" className="text-sm text-danger-500">{error}</p>}
    </div>
  );
}

function OpenItems({ runId, gate, rows, onJump, onDecided }: {
  runId: string; gate: CrsIssueGate; rows: CrsRow[]; onJump: (row: CrsRow) => void; onDecided: () => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const split = splitOpenItems(gate, rows);
  // Standard names in this list come from the documents: they are drawn on this local screen only and never logged.
  const shown = otherItemLines(split.others);
  const done = split.comments.length === 0 && split.unnumbered.length === 0 && split.others.length === 0;
  async function decideOthers(decision: "accept" | "reject") {
    if (reason.trim().length < MIN_SIGN_REASON) { setError(`Write your reason first (${MIN_SIGN_REASON} characters at least).`); return; }
    setBusy(true);
    setError(null);
    const failed: string[] = [];
    for (const item of split.others) {
      const result = await reviewsApi.decideCrsFinding(runId, item.finding_id, decision, reason.trim());
      if (!result.ok) failed.push(result.error.message);
    }
    setBusy(false);
    if (failed.length) setError(`${plural(failed.length, "item was", "items were")} not recorded: ${failed[0]}`);
    else setReason("");
    await onDecided();
  }
  return (
    <div className={`${box} ${done ? "border-ink-700" : "border-warn-500/40"}`} data-testid="sign-items">
      <p className="text-sm text-slateish-100">
        <Mark done={done} /> {done ? "Every comment has a decision." : split.comments.length > 0 ? (
          <>
            {split.comments.length === 1 ? "Comment " : "Comments "}
            {split.comments.map((n, i) => (
              <span key={n}>
                {i > 0 ? ", " : ""}
                <button type="button" className={link} onClick={() => { const row = split.rowFor.get(n); if (row) onJump(row); }}>{n}</button>
              </span>
            ))}
            {split.comments.length === 1 ? " still needs a decision." : " still need a decision."}
            {" "}Keep or remove them on the sheet, then Save decisions.
          </>
        ) : "Every comment on the sheet has a decision."}
      </p>
      {split.unnumbered.length > 0 && (
        <div className="space-y-1 text-sm text-slateish-200" data-testid="sign-unnumbered">
          <p>{plural(split.unnumbered.length, "comment on this sheet has", "comments on this sheet have")} no comment number and no decision yet. Open each one:</p>
          <ul className="list-disc pl-5 text-xs">
            {split.unnumbered.map((row) => (
              <li key={row.key}>
                <button type="button" className={link} onClick={() => onJump(row)}>{row.item || row.pageOrSection || "Open the row"}</button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {split.others.length > 0 && (
        <div className="space-y-2 text-sm text-slateish-200">
          <p>
            {plural(split.others.length, "other item", "other items")} on the issued copy {split.others.length === 1 ? "is" : "are"} not on this sheet and {split.others.length === 1 ? "has" : "have"} no decision:
          </p>
          <ul className="list-disc pl-5 text-xs text-slateish-300">
            {shown.lines.map((line) => <li key={line.id}>{line.text}</li>)}
            {shown.more > 0 && <li>and {shown.more} more of {shown.total} ({shown.moreKinds})</li>}
          </ul>
          <div className="flex flex-wrap items-center gap-2">
            <input aria-label="Reason for the other items" value={reason} placeholder="One reason for all of them"
              onChange={(e) => setReason(e.target.value)} className={input} />
            <button type="button" disabled={busy} aria-label={`Keep all ${plural(shown.total, "other item", "other items")}`} onClick={() => void decideOthers("accept")} className={button}>Keep them</button>
            <button type="button" disabled={busy} aria-label={`Leave all ${plural(shown.total, "other item", "other items")} off`} onClick={() => void decideOthers("reject")} className={button}>Leave them off</button>
          </div>
        </div>
      )}
      {error && <p role="alert" className="text-sm text-danger-500">{error}</p>}
    </div>
  );
}

export function BeforeYouSign({ run, rows, state, onRunChanged, onJump }: {
  run: ReviewRunSummary;
  rows: CrsRow[];
  state: IssueGateState;
  /** The run was changed (the final code): read it again. */
  onRunChanged: () => void;
  /** Open a comment row (its evidence) on the sheet. */
  onJump: (row: CrsRow) => void;
}) {
  const { gate, error, reload } = state;
  const left = signLeft(state, run, rows);
  return (
    <section aria-labelledby="sign-title" className="space-y-2 rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-4" data-testid="before-you-sign">
      <h2 id="sign-title" className="text-base font-semibold text-slateish-100">
        Before you sign{left.length === 0 ? ": all done ✅" : ""}
      </h2>
      {!gate ? (
        <p role="alert" className="flex flex-wrap items-center gap-2 text-sm text-danger-500">
          {error ?? "Checking what is left…"}
          {error && <button type="button" className={link} onClick={() => void reload()}>Check again</button>}
        </p>
      ) : (
        <>
          <FinalCode key={run.review_run_id} run={run} onChanged={() => { onRunChanged(); void reload(); }} />
          <UnreadPages runId={run.review_run_id} gate={gate} onDecided={reload} />
          <OpenItems runId={run.review_run_id} gate={gate} rows={rows} onJump={onJump} onDecided={reload} />
          {left.length > 0 && (
            <p className="text-sm text-slateish-300" data-testid="sign-left">Sign and export waits until you {left.join("; ")}.</p>
          )}
        </>
      )}
    </section>
  );
}
