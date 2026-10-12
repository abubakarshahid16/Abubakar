/**
 * #645: checks the AI proposed for clause sentences the reviews could not
 * decide, each already verified by code against the sentence, waiting for an
 * engineer.
 *
 * WHAT IT REFUSES TO DO:
 *  - Call a draft a requirement. Until accepted it is labelled a proposal and
 *    no review decides anything on it.
 *  - Hide the words. The clause sentence and the quoted words the limit
 *    stands on are shown next to the proposal, so the engineer judges the
 *    clause, not the model.
 *  - Let a non-administrator decide. Accept and reject are admin actions on
 *    the server; the buttons are shown only to an administrator.
 */
import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client";
import { ErrorState, Spinner } from "../states";
import type { ApiError, ClauseCheckDraft } from "../../types/api";

type Load =
  | { state: "loading" }
  | { state: "error"; error: ApiError }
  | { state: "ready"; rows: ClauseCheckDraft[] };

function limitText(d: ClauseCheckDraft): string {
  return [d.field, d.operator ?? "", d.value, d.unit ?? ""].filter(Boolean).join(" ");
}

export function ClauseCheckDrafts({ isAdmin = false }: { isAdmin?: boolean }) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const result = await api.clauseCheckDrafts();
    if (result.ok) setLoad({ state: "ready", rows: result.data });
    else setLoad({ state: "error", error: result.error });
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const decide = async (id: string, decision: "accept" | "reject") => {
    setBusy(id);
    setFailure(null);
    const result = await api.decideClauseCheck(id, decision);
    setBusy(null);
    if (!result.ok) {
      setFailure(result.error.message || "Could not record the decision.");
      return;
    }
    await refresh();
  };

  if (load.state === "loading") return <Spinner />;
  if (load.state === "error") {
    return <ErrorState error={load.error} onRetry={() => void refresh()} />;
  }

  return (
    <section aria-labelledby="clause-check-drafts" className="flex flex-col gap-2">
      <h3 id="clause-check-drafts" className="text-sm font-medium">
        Checks proposed by the AI, waiting for an engineer ({load.rows.length})
      </h3>
      <p className="text-xs opacity-70">
        For clause sentences the reviews could not decide. Code has checked each
        figure against the quoted words; no review uses a proposal until an
        engineer accepts it. Accepting writes a confirmed requirement and keeps
        the old sentence as a superseded version.
      </p>
      {failure && <p role="alert" className="text-xs text-red-400">{failure}</p>}
      {load.rows.length === 0 ? (
        <p className="text-xs opacity-70">No proposals are waiting.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {load.rows.map((d) => (
            <li key={d.id} data-testid={`clause-check-${d.id}`}
                className="rounded border border-ink-700 p-2 text-xs">
              <p>
                <span className="font-medium">Proposed check: {limitText(d)}</span>
                {d.condition ? <span> - only {d.condition}</span> : null}
              </p>
              <p className="opacity-70">
                Clause {d.clause ?? "not identified"}{d.page != null ? `, page ${d.page}` : ""}:
                {" "}{d.source_text}
              </p>
              <p className="opacity-70">Stands on the words: &ldquo;{d.quote}&rdquo;</p>
              {isAdmin && (
                <div className="mt-1 flex gap-2">
                  <button type="button" disabled={busy === d.id}
                          onClick={() => void decide(d.id, "accept")}>
                    Accept as a requirement
                  </button>
                  <button type="button" disabled={busy === d.id}
                          onClick={() => void decide(d.id, "reject")}>
                    Reject
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
