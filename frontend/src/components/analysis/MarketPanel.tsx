/**
 * Public market information.
 *
 * Two things this panel must never do: describe a fixture as live, and let a
 * query leave the machine that the user has not read. This build is offline -
 * WEB_SEARCH_ENABLED=false and ALLOW_PUBLIC_EGRESS=false - so every finding is a
 * sample and says so on every row, and the banner says so above them all.
 *
 * The outbound query (NABAA-SUNDAY-POC-EXECUTION.md section 3, control 9 and
 * 16) is built ONLY from the public-market form. Nothing from the documents is
 * used to form it. Before anything could be sent, the EXACT string is shown in
 * a modal and the user confirms - and in this build Confirm is disabled,
 * because egress is blocked.
 *
 * Findings appear here, under Public market information, and never among
 * documented requirements. A snippet is preliminary evidence; the verification
 * column says in words whether the underlying page was read.
 */
import { useEffect, useId, useRef, useState } from "react";

import type { EgressState, MarketFinding, MarketVerification, PublicMarketQuery } from "../../types/analysis";

const VERIFICATION: Record<MarketVerification, string> = {
  source_read: "source read",
  snippet_only: "snippet only",
  source_not_verified: "source not verified",
};

function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-ink-500 bg-ink-800 px-2 py-0.5 font-mono text-[11px] uppercase tracking-wider text-slateish-300">
      {children}
    </span>
  );
}

function SampleTag() {
  return (
    <span className="rounded border border-ink-500 px-1 font-mono text-[10px] uppercase tracking-wider text-slateish-400">
      Sample
    </span>
  );
}

function FindingRow({ f }: { f: MarketFinding }) {
  return (
    <li className="border-t border-ink-700/60 py-2.5 first:border-t-0">
      <div className="flex flex-wrap items-baseline gap-2">
        <SampleTag />
        <p className="model-prose text-sm text-slateish-200">{f.claim}</p>
      </div>
      <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        <dt className="text-slateish-500">publisher</dt>
        <dd className="text-slateish-300">{f.publisher}</dd>
        <dt className="text-slateish-500">published</dt>
        <dd className="text-slateish-300">{f.published_at ?? "—"}</dd>
        <dt className="text-slateish-500">retrieved</dt>
        <dd className="text-slateish-300">{f.retrieved_at}</dd>
        <dt className="text-slateish-500">verification</dt>
        <dd className="text-slateish-300">{VERIFICATION[f.verification]}</dd>
        <dt className="text-slateish-500">url</dt>
        <dd>
          <code
            title="offline build; link not followed"
            className="break-all font-mono text-[11px] text-slateish-400"
          >
            {f.url}
          </code>
        </dd>
      </dl>
    </li>
  );
}

function QueryForm({ onPreview }: { onPreview: (q: PublicMarketQuery) => void }) {
  const [query, setQuery] = useState("");
  const [country, setCountry] = useState("");
  const [freshness, setFreshness] = useState("");
  const qId = useId();
  const cId = useId();
  const fId = useId();
  const trimmed = query.trim();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!trimmed) return;
    const days = freshness.trim() === "" ? null : Number(freshness);
    onPreview({
      query: trimmed,
      country: country.trim() || null,
      freshness_days: days !== null && Number.isFinite(days) && days > 0 ? Math.floor(days) : null,
    });
  }

  return (
    <form onSubmit={submit} className="mt-4 space-y-3 rounded border border-ink-700 p-3">
      <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slateish-300">
        Public market query
      </h4>
      <p className="text-xs text-slateish-300">
        This query is built ONLY from what you type here. Nothing from your documents is ever
        used to form it.
      </p>
      <div>
        <label htmlFor={qId} className="block text-xs text-slateish-400">
          Query
        </label>
        <input
          id={qId}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="mt-1 w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-slateish-200"
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor={cId} className="block text-xs text-slateish-400">
            Country (optional)
          </label>
          <input
            id={cId}
            type="text"
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            className="mt-1 w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-slateish-200"
          />
        </div>
        <div>
          <label htmlFor={fId} className="block text-xs text-slateish-400">
            Freshness, days (optional)
          </label>
          <input
            id={fId}
            type="number"
            min={1}
            value={freshness}
            onChange={(e) => setFreshness(e.target.value)}
            className="mt-1 w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-slateish-200"
          />
        </div>
      </div>
      <button
        type="submit"
        disabled={!trimmed}
        className="rounded border border-ink-500 px-3 py-1.5 text-sm text-slateish-200 hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        Preview exact outbound query
      </button>
    </form>
  );
}

/** The exact string as it would be serialised. Nothing is added to it. */
function serialise(q: PublicMarketQuery): string {
  return JSON.stringify(q);
}

function ConfirmDialog({
  query,
  egress,
  onConfirm,
  onCancel,
}: {
  query: PublicMarketQuery;
  egress: EgressState;
  onConfirm?: () => void;
  onCancel?: () => void;
}) {
  const blocked = egress.allow_public_egress === false;
  const titleId = useId();
  const descId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      onCancel?.();
      return;
    }
    if (e.key !== "Tab") return;
    // Focus trapped to the two buttons. A disabled Confirm is skipped by the
    // browser anyway, so focus stays on Cancel.
    const targets = [cancelRef.current, confirmRef.current].filter(
      (el): el is HTMLButtonElement => el !== null && !el.disabled,
    );
    if (targets.length === 0) return;
    e.preventDefault();
    const idx = targets.indexOf(document.activeElement as HTMLButtonElement);
    const next = e.shiftKey ? (idx <= 0 ? targets.length - 1 : idx - 1) : (idx + 1) % targets.length;
    targets[next].focus();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/80 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
        onKeyDown={onKeyDown}
        className="w-full max-w-lg rounded-lg border border-ink-500 bg-ink-850 p-4"
      >
        <h4 id={titleId} className="text-sm font-semibold text-slateish-200">
          Confirm outbound query
        </h4>
        <p id={descId} className="mt-1 text-xs text-slateish-300">
          This is the exact text that would leave the machine. Nothing else.
        </p>
        <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-all rounded border border-ink-600 bg-ink-900 p-3 font-mono text-xs text-slateish-100">
          {serialise(query)}
        </pre>
        {blocked && (
          <p role="status" className="mt-2 text-xs text-warn-500">
            Public egress is blocked in this build.
          </p>
        )}
        <div className="mt-3 flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="rounded border border-ink-500 px-3 py-1.5 text-sm text-slateish-200 hover:bg-ink-700"
          >
            Cancel
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            disabled={blocked}
            aria-disabled={blocked}
            title={blocked ? "Public egress is blocked in this build." : undefined}
            className="rounded border border-signal-500/60 px-3 py-1.5 text-sm text-signal-300 hover:bg-signal-500/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Confirm and send
          </button>
        </div>
      </div>
    </div>
  );
}

export function MarketPanel({
  findings,
  egress,
  onPreviewQuery,
  pendingQuery,
  onConfirmQuery,
  onCancelQuery,
}: {
  findings: MarketFinding[];
  egress: EgressState;
  onPreviewQuery?: (q: PublicMarketQuery) => void;
  pendingQuery?: PublicMarketQuery | null;
  onConfirmQuery?: () => void;
  onCancelQuery?: () => void;
}) {
  return (
    <section aria-label="Public market information" className="rounded-lg border border-ink-600 bg-ink-850 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-slateish-300">
          Public market information
        </h3>
        <div className="flex flex-wrap gap-1.5" aria-live="polite">
          {egress.web_search_enabled === false && <Pill>Web search off</Pill>}
          {egress.allow_public_egress === false && <Pill>Public egress blocked</Pill>}
        </div>
      </div>

      <div role="note" className="mt-3 rounded border-2 border-warn-500/70 bg-warn-500/10 px-3 py-2 text-sm text-warn-500">
        <span className="font-semibold">SAMPLE DATA &mdash; NOT LIVE.</span> This machine is
        offline. Every row below is an illustrative sample and must not be described as live
        market data.
      </div>

      {findings.length === 0 ? (
        <p className="mt-3 text-sm text-slateish-500">No market sample loaded.</p>
      ) : (
        <ul className="mt-3">
          {findings.map((f, i) => (
            <FindingRow key={`${f.url}-${i}`} f={f} />
          ))}
        </ul>
      )}

      <p className="mt-3 border-t border-ink-700 pt-2 text-xs text-slateish-500">
        Public web findings cannot prove internal project compliance. Snippets are preliminary
        evidence; the verification column says whether the page was read.
      </p>

      {onPreviewQuery && <QueryForm onPreview={onPreviewQuery} />}

      {pendingQuery && (
        <ConfirmDialog query={pendingQuery} egress={egress} onConfirm={onConfirmQuery} onCancel={onCancelQuery} />
      )}
    </section>
  );
}
