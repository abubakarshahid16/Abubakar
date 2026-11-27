/**
 * The Administration page's "Technical query reviewers" section (owner's ask, 26 Nov 2026 21:29 PKT; lead-4): who may confirm a
 * query's question, keep or reject its evidence, approve and send its answer. The role and its routes existed
 * (`GET/PUT/DELETE /api/technical-queries/reviewers`), but no screen gave it, so nobody held it and Confirm was refused for everyone.
 *
 * WHAT THIS SCREEN DOES NOT DECIDE: the server's rule that an administrator cannot give the role to themselves ("qualification is
 * another person's call"). The administrator's own row says so and offers no button; the server refuses it anyway, and any refusal
 * is shown in the server's own words. Shown only when technical queries are switched on (the routes answer "not found" otherwise).
 */
import { useCallback, useEffect, useState } from "react";

import { hasArrayField, request } from "../../api/core";
import type { AdminUser } from "../../types/admin";
import type { AuthStatus } from "../../types/api";
import { Button } from "../../components/kit/Kit";

interface Reviewer { id: string; email: string; display_name?: string | null }
type Rows = { items: Reviewer[] };

export const SELF_GRANT_WORDS =
  "You cannot give yourself this role: another administrator gives it (the server's rule: being qualified is someone else's call).";

export function TechnicalQueryReviewersSection({ users }: { users: AdminUser[] | null }) {
  const [reviewers, setReviewers] = useState<Set<string> | null | "off">(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [meId, setMeId] = useState<string | null>(null); // the signed-in administrator: their own row offers no grant

  const load = useCallback(async () => {
    // the shape is checked before use: an answer without its list is a failure said in words, never a crash (integrator, update 17)
    const r = await request<Rows>("/technical-queries/reviewers", undefined, hasArrayField("items"));
    if (r.ok) { setReviewers(new Set(r.data.items.map((x) => x.id))); setFailure(null); }
    else if (!r.disconnected && r.error.code === "not_found") setReviewers("off"); // the feature is switched off: no section
    else setFailure(r.error.message);
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { void request<AuthStatus>("/auth/me").then((r) => { if (r.ok) setMeId(r.data.user?.id ?? null); }); }, []);

  async function change(userId: string, grant: boolean) {
    setBusy(userId); setFailure(null);
    const r = await request<Rows>(`/technical-queries/reviewers/${encodeURIComponent(userId)}`, { method: grant ? "PUT" : "DELETE" }, hasArrayField("items"));
    setBusy(null);
    if (r.ok) setReviewers(new Set(r.data.items.map((x) => x.id)));
    else setFailure(r.error.message);
  }

  if (reviewers === "off") return null;
  const active = (users ?? []).filter((u) => u.active);
  return (
    <section aria-labelledby="tq-reviewers-title" data-testid="tq-reviewers"
      className="rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4">
      <h2 id="tq-reviewers-title" className="text-sm font-semibold text-slateish-200">Technical query reviewers</h2>
      <p className="mt-1 text-xs text-slateish-400">
        A reviewer confirms a query&apos;s question, keeps or rejects its evidence, and approves and sends its answer. Without one, the
        Confirm button is refused for everyone.
      </p>
      {failure && <p role="alert" className="mt-2 text-sm text-danger-500">{failure}</p>}
      {reviewers === null && !failure ? <p className="mt-2 text-sm text-slateish-400">Reading who holds the role…</p> : null}
      {reviewers instanceof Set && (
        <>
          <p data-testid="tq-reviewers-count" className="mt-2 text-sm text-slateish-200">
            {reviewers.size === 0 ? "Nobody holds the role yet." : `${reviewers.size} of ${active.length} active user${active.length === 1 ? "" : "s"} hold the role.`}
          </p>
          <ul className="mt-2 divide-y divide-ink-700/70">
            {active.map((u) => {
              const holds = reviewers.has(u.user_id);
              const self = u.user_id === meId;
              return (
                <li key={u.user_id} data-testid="tq-reviewer-row" className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                  <span className="text-slateish-200">{u.email}{u.is_admin ? " · administrator" : ""}</span>
                  <span className="flex items-center gap-2">
                    <span className={holds ? "text-signal-300" : "text-slateish-400"}>{holds ? "Reviewer" : "Not a reviewer"}</span>
                    {self && !holds ? (
                      <span className="text-xs text-slateish-400">{SELF_GRANT_WORDS}</span>
                    ) : (
                      <Button variant="secondary" size="sm" disabled={busy !== null} onClick={() => void change(u.user_id, !holds)}>
                        {busy === u.user_id ? "Saving…" : holds ? "Remove the role" : "Give the role"}
                      </Button>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
