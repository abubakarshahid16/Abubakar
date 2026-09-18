import { useEffect, useId, useRef, useState } from "react";
import type { MarketPreview, MarketSearchResult } from "../../api/client";
import type { EgressState, PublicMarketQuery } from "../../types/analysis";
import { sampleReason, SAMPLE_BANNER_TAIL, PREVIEW_UNREACHABLE, NO_SAFE_PHRASE, CANCEL_SENDS_NOTHING, FAILURE_NO_ROWS, NO_RESULTS, searchDisabledReason, TierTrail, SearchRow } from "./MarketPanelPrimitives";

export function QueryForm({ onPreview }: { onPreview: (q: PublicMarketQuery) => void }) {
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
    <form onSubmit={submit} className="mt-4 space-y-3 rounded-[var(--radius-xs)] border border-ink-700 p-3">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-slateish-300">
        Public market query
      </h4>
      <p className="text-xs text-slateish-300">
        This query is built ONLY from what you type here. Nothing from your documents is ever
        used to form it.
      </p>
      <p className="text-xs text-slateish-400">
        Typing sends nothing. Enter opens the preview; only the button inside the preview can
        send.
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
          className="mt-1 w-full rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-slateish-200"
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
            className="mt-1 w-full rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-slateish-200"
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
            className="mt-1 w-full rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-slateish-200"
          />
        </div>
      </div>
      <button
        type="submit"
        disabled={!trimmed}
        className="rounded-[var(--radius-xs)] border border-ink-500 px-3 py-1.5 text-sm text-slateish-200 hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        Preview exact outbound query
      </button>
    </form>
  );
}

// ----------------------------------------------------------------- preview

export type PreviewState =
  | { s: "loading" }
  | { s: "ready"; data: MarketPreview }
  | { s: "unreachable" }
  | { s: "error"; message: string };

export function ConfirmDialog({
  query,
  egress,
  preview,
  onSend,
  onCancel,
}: {
  query: PublicMarketQuery;
  egress: EgressState;
  preview: PreviewState;
  onSend: () => void;
  onCancel?: () => void;
}) {
  // BOTH FLAGS, because the backend gates the request on both:
  // `market_transport.transport()` returns None unless
  // `market_live_enabled AND market_allow_public_egress`. Reading only
  // `allow_public_egress` here left a real state - web search off, egress
  // allowed - in which Confirm rendered live and titled as sendable, sent,
  // and came back `enabled: false` with fixtures. Offering a send that cannot
  // happen and then showing samples as its outcome is the panel answering for
  // the backend and getting it wrong.
  const blocked =
    egress.allow_public_egress === false || egress.web_search_enabled === false;
  /** Which flag blocked it, so the notice names the one the operator must
   *  flip rather than the one this component happened to check first. */
  const blockedReason = sampleReason(egress);
  const noSafePhrase = preview.s === "ready" && preview.data.phrase === null;
  const titleId = useId();
  const descId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  /** The element that had focus when this dialog opened. A modal that takes
   *  focus must give it back: without this, closing the dialog dropped focus on
   *  <body> and a keyboard reader lost their place in the query form. */
  const returnFocusTo = useRef<HTMLElement | null>(null);

  // The trap below already holds focus inside the dialog. This is the other
  // half of it: capture the trigger on open, restore it on close. The dialog is
  // unmounted by the parent on every close path - Confirm, Cancel and Escape
  // all end in the same `pendingQuery: null` - so one cleanup covers all three
  // rather than three handlers that can drift apart.
  useEffect(() => {
    const active = document.activeElement;
    returnFocusTo.current = active instanceof HTMLElement ? active : null;
    cancelRef.current?.focus();
    return () => {
      const prev = returnFocusTo.current;
      returnFocusTo.current = null;
      // A trigger that has since been removed from the document cannot take
      // focus; forcing it would throw and leave focus nowhere.
      if (prev !== null && prev.isConnected) prev.focus();
    };
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
        className="w-full max-w-lg rounded-[var(--radius-md)] border border-ink-500 bg-ink-850 p-4"
      >
        <h4 id={titleId} className="text-sm font-semibold text-slateish-200">
          Confirm outbound query
        </h4>
        <p id={descId} className="mt-1 text-xs text-slateish-300">
          This is the exact text that would leave the machine. Nothing else.
        </p>

        {/* What the reader typed, before any scrubbing, so the two strings can
            be compared side by side. This one is the reader's own and is
            always available; the one below is the backend's. */}
        <p className="mt-3 text-xs uppercase tracking-wider text-slateish-500">What you typed</p>
        <p className="mt-1 break-words text-sm text-slateish-200">{query.query}</p>

        <div aria-live="polite">
          {preview.s === "loading" && (
            <p className="mt-3 text-xs text-slateish-400">Checking what can safely be sent&hellip;</p>
          )}

          {preview.s === "unreachable" && (
            <p className="mt-3 text-xs text-warn-500">{PREVIEW_UNREACHABLE}</p>
          )}

          {preview.s === "error" && <p className="mt-3 text-xs text-warn-500">{preview.message}</p>}

          {preview.s === "ready" && preview.data.phrase === null && (
            <p className="mt-3 text-xs text-danger-500">{NO_SAFE_PHRASE}</p>
          )}

          {preview.s === "ready" && preview.data.phrase !== null && (
          <>
            <p className="mt-3 text-xs uppercase tracking-wider text-slateish-500">
              The phrase that would be sent
            </p>
            <p className="mt-1 break-words text-sm text-slateish-100">{preview.data.phrase}</p>
            {/* ONE BLOCK PER TIER, because that is what actually leaves. A
                search builds one payload per configured tier, so a single
                block meant the reader approved one object while up to three
                others went - and this dialog is the approval. Each is
                labelled with the tier it belongs to, so "would be asked of"
                and "here is what it would be asked" are the same list. */}
            <p className="mt-3 text-xs uppercase tracking-wider text-slateish-500">
              {preview.data.payloads.length === 1
                ? "The exact outbound payload, as the backend states it"
                : `The exact outbound payloads, as the backend states them (${preview.data.payloads.length})`}
            </p>
            {preview.data.payloads.map((entry) => (
              <div key={entry.tier} className="mt-2">
                <p className="text-xs text-slateish-400">
                  To {entry.provider_label}:
                </p>
                <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 p-3 font-mono text-xs text-slateish-100">
                  {JSON.stringify(entry.payload, null, 2)}
                </pre>
              </div>
            ))}
            {/* NO SEPARATE SCOPE LINE. `country` and `freshness_days` are
                inside each payload above, stated by the backend, because
                /api/market/preview now takes them. The panel used to list
                them itself and attribute them to itself - a workaround for
                the preview not carrying them, and one that asked the reader
                to trust the panel about what the request contained. */}
            {preview.data.payloads.length === 0 && (
              <p className="mt-2 text-xs text-warn-500">
                No tier is configured in this build, so there is nothing to
                send and nothing would be sent.
              </p>
            )}
            {preview.data.tiers_unconfigured.length > 0 && (
              <p className="mt-2 text-xs text-slateish-400">
                Not configured here, and not contacted:{" "}
                {preview.data.tiers_unconfigured
                  .map((t) => preview.data.tier_labels[t] ?? t)
                  .join(", ")}
                .
              </p>
            )}
          </>
          )}
        </div>

        {blocked && (
          <p role="status" className="mt-2 text-xs text-warn-500">
            {blockedReason} Nothing can be sent until it is on.
          </p>
        )}

        <p className="mt-3 text-xs text-slateish-400">{CANCEL_SENDS_NOTHING}</p>

        <div className="mt-3 flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="rounded-[var(--radius-xs)] border border-ink-500 px-3 py-1.5 text-sm text-slateish-200 hover:bg-ink-700"
          >
            Cancel
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onSend}
            disabled={blocked || noSafePhrase}
            aria-disabled={blocked || noSafePhrase}
            title={
              blocked
                ? blockedReason
                : noSafePhrase
                  ? NO_SAFE_PHRASE
                  : undefined
            }
            className="rounded-[var(--radius-xs)] border border-signal-500/60 px-3 py-1.5 text-sm text-signal-300 hover:bg-signal-500/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Confirm and send
          </button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ results

export type SearchState =
  | { s: "idle" }
  | { s: "running" }
  | { s: "ready"; data: MarketSearchResult }
  | { s: "unreachable" }
  | { s: "error"; message: string }
  | { s: "not_sent" };

export function SampleBanner({ reason }: { reason: string }) {
  return (
    <div role="note" className="mt-3 rounded-[var(--radius-xs)] border-2 border-warn-500/70 bg-warn-500/10 px-3 py-2 text-sm text-warn-500">
      <span className="font-semibold">SAMPLE DATA &mdash; NOT LIVE.</span>{" "}
      {reason} {SAMPLE_BANNER_TAIL}
    </div>
  );
}

/**
 * What came back from a search, or why nothing did.
 *
 * The order of the branches is the order of the guarantees. `failure` is
 * checked FIRST and returns before any row can be drawn, so there is no
 * arrangement of the payload in which a failure and a row appear together -
 * including the arrangement where `rows` still carries the samples.
 */
export function SearchOutcome({ result, egress }: { result: MarketSearchResult; egress: EgressState }) {
  if (result.failure !== null) {
    return (
      <div className="mt-3">
        <p className="text-sm text-danger-500">{result.failure}</p>
        <p className="mt-1 text-xs text-slateish-400">{FAILURE_NO_ROWS}</p>
        <TierTrail result={result} />
      </div>
    );
  }

  if (result.enabled === false) {
    return (
      <div className="mt-1">
        <SampleBanner reason={searchDisabledReason(egress)} />
        {result.rows.length > 0 && (
          <ul className="mt-3">
            {result.rows.map((row, i) => (
              <SearchRow key={`${row.url}-${i}`} row={row} />
            ))}
          </ul>
        )}
      </div>
    );
  }

  if (result.rows.length === 0) {
    return (
      <div className="mt-3">
        <p className="text-sm text-slateish-300">{NO_RESULTS}</p>
        <TierTrail result={result} />
      </div>
    );
  }

  return (
    <div className="mt-3">
      <TierTrail result={result} />
      <ul className="mt-1">
        {result.rows.map((row, i) => (
          <SearchRow key={`${row.url}-${i}`} row={row} />
        ))}
      </ul>
    </div>
  );
}

// -------------------------------------------------------------------- panel
