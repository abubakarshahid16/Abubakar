/**
 * #620 (owner's option a, 19 Oct 2026): the Administration page's list of
 * Company standards waiting for an administrator's confirmation, and the one
 * action that releases one for reviews.
 *
 * WHAT IS LISTED, SAID ON THE SCREEN: a Company standard a non-administrator
 * uploaded on or after the cut-off (`confirm_from`). Standards uploaded
 * before it count as confirmed and are not listed - the boundary line says
 * so, so an empty list never reads as "every standard has been checked".
 * A held standard stays readable by its disciplines; only reviews skip it,
 * and each review that skipped one says so on its own "How this was reviewed".
 *
 * Confirming is the server's: idempotent and audited, admin-only at the
 * route (`POST /api/admin/company-standards/{id}/confirm`). The list is read
 * again after every confirm, so the screen shows the server's answer.
 */
import { useCallback, useEffect, useState } from "react";

import type { AdminClient, HeldCompanyStandard, LoadFailure } from "../../types/admin";

/** "2026-10-18T00:00:00" -> "2026-10-18"; "" for nothing. */
function day(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : "";
}

export function CompanyStandardsSection({ client }: { client: AdminClient }) {
  const [rows, setRows] = useState<HeldCompanyStandard[] | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [confirmFrom, setConfirmFrom] = useState<string | null>(null);
  const [failure, setFailure] = useState<LoadFailure | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ error: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    if (!client.heldCompanyStandards) return;
    const r = await client.heldCompanyStandards();
    // A body this section cannot use is a failure, never "nothing waiting".
    if (r.ok && Array.isArray(r.data?.standards) && typeof r.data.total === "number") {
      setRows(r.data.standards);
      setTotal(r.data.total);
      setConfirmFrom(r.data.confirm_from ?? null);
      setFailure(null);
      return;
    }
    setRows(null);
    setTotal(null);
    setFailure(
      !r.ok && r.disconnected ? { kind: "offline" }
      : !r.ok && r.error.code === "not_found" ? { kind: "missing" }
      : !r.ok ? { kind: "failed", code: r.error.code, message: r.error.message }
      : { kind: "failed", code: "internal", message: "The backend answered with something this screen cannot read." });
  }, [client]);

  useEffect(() => { void load(); }, [load]);

  async function confirm(row: HeldCompanyStandard) {
    if (!client.confirmCompanyStandard) return;
    const name = row.filename ?? row.id;
    if (!window.confirm(`Use "${name}" in reviews from the next run? This is recorded under your name.`)) return;
    setBusy(row.id);
    setMessage(null);
    const r = await client.confirmCompanyStandard(row.id);
    setBusy(null);
    if (!r.ok) {
      setMessage({ error: true, text: r.disconnected ? "The backend is not running, so nothing was confirmed." : r.error.message });
      return;
    }
    setMessage({
      error: false,
      text: r.data.confirmed ? `Confirmed: "${name}" is used from the next review.` : `"${name}" was already confirmed.`,
    });
    await load();
  }

  if (!client.heldCompanyStandards) return null;

  const cutoff = day(confirmFrom);
  return (
    <section aria-labelledby="admin-held-standards-heading" className="space-y-2" data-testid="admin-held-standards">
      <h2 id="admin-held-standards-heading" className="text-sm font-semibold text-slateish-200">
        Company standards waiting for confirmation
      </h2>
      <p className="text-xs text-slateish-400" data-testid="admin-held-boundary">
        {cutoff
          ? `A Company standard a non-administrator uploads on or after ${cutoff} is not used in reviews until an administrator confirms it. Company standards uploaded before ${cutoff} count as confirmed and are not listed here.`
          : "Every Company standard a non-administrator uploaded waits here until an administrator confirms it."}
      </p>

      {failure && (
        <p role="alert" className="rounded-[var(--radius-sm)] border border-warn-500/40 bg-warn-500/10 px-3 py-2 text-xs text-warn-500">
          {failure.kind === "offline"
            ? "The backend is not running, so the waiting standards cannot be listed."
            : failure.kind === "missing"
              ? "This backend does not serve the Company standard confirmation list."
              : failure.message}
        </p>
      )}
      {!failure && rows === null && <p className="text-xs text-slateish-400">Loading…</p>}

      {rows !== null && total !== null && (
        <>
          <p className="text-sm text-slateish-200" data-testid="admin-held-count">
            {total === 0
              ? "No Company standard is waiting for confirmation."
              : `${total.toLocaleString()} Company ${total === 1 ? "standard is" : "standards are"} waiting for confirmation`
                + (rows.length < total ? ` (showing ${rows.length.toLocaleString()}).` : ".")}
          </p>
          {rows.length > 0 && (
            <ul className="divide-y divide-ink-700 rounded-[var(--radius-md)] border border-ink-600">
              {rows.map((row) => (
                <li key={row.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm" data-testid={`admin-held-${row.id}`}>
                  <span className="font-medium text-slateish-100">{row.filename ?? row.id}</span>
                  {row.uploaded_at && <span className="text-xs text-slateish-400">uploaded {day(row.uploaded_at)}</span>}
                  <button type="button" disabled={busy !== null || !client.confirmCompanyStandard}
                    onClick={() => void confirm(row)}
                    className="ml-auto rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-xs text-slateish-100 disabled:opacity-50">
                    {busy === row.id ? "Confirming…" : "Confirm for reviews"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {message && (
        <p role={message.error ? "alert" : "status"} className={`text-xs ${message.error ? "text-danger-500" : "text-slateish-300"}`}>
          {message.text}
        </p>
      )}
    </section>
  );
}
