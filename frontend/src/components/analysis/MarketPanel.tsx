/**
 * Public market information.
 *
 * Two things this panel must never do: describe a fixture as live, and let a
 * query leave the machine that the user has not read. Both are now testable
 * properties rather than consequences of the build being offline, because the
 * providers behind /api/market/search are real and can be switched on.
 *
 * WHAT THIS PANEL SENDS, AND WHEN. Exactly one call can leave the machine -
 * `market.search` - and it is reachable from ONE explicit click on "Confirm
 * and send" inside the confirmation dialog. There is no debounce, no
 * submit-on-send, no blur handler and no effect that dispatches it. Enter in
 * the query field OPENS THE PREVIEW; it cannot send. `market.preview` is a
 * read on this machine's own backend, performs no egress, and is the only
 * thing typing or submitting can reach.
 *
 * AND IT DOES NOT SEND WHAT IT CANNOT SHOW. The payload in the dialog is the
 * BACKEND'S (`preview.payload`), not a client-side re-serialisation of the
 * form: a reconstruction is a guess at what leaves the machine, and a guess
 * that has drifted is a lie told with confidence. So when the preview has not
 * arrived, Confirm sends nothing at all and the panel says so. The button is
 * left live in that state rather than disabled on purpose - the reader gets a
 * sentence explaining that nothing was sent, which is more use than a dead
 * control with no explanation. When the preview arrives and its phrase is
 * NULL, no search is possible and Confirm is disabled outright.
 *
 * PROVENANCE IS PER ROW, ALWAYS. `provider_label` is printed on every row
 * exactly as sent - never inferred from the url or the publisher, never
 * omitted. A "reference - background only" row additionally carries a
 * sentence of its own saying it is not a market finding, because an
 * unlabelled encyclopedia line in a compliance tool discredits every other
 * row on the screen.
 *
 * NULLS RENDER AS NOTHING. `published` is nullable; a null withholds the
 * label and the value together - not a dash, not "N/A", and never today's
 * date, which would date an undated page.
 *
 * FALLBACK IS VISIBLE. `tiers_attempted` against `tiers_answered` is printed,
 * so a reader can see that the general web search was tried and did not
 * answer. Tier-3 background rows are never presented as market findings.
 *
 * A FIXTURE IS NEVER A FALLBACK. Sample rows appear in exactly two states:
 * the legacy `findings` prop (this build's /market/findings fixture), and a
 * search that came back `enabled: false`. After a search that FAILED there
 * are no rows at all - a sample presented as the answer to a failed live
 * search is the one behaviour that would turn this feature into a liability.
 *
 * Findings appear here, under Public market information, and never among
 * documented requirements. A snippet is preliminary evidence; the
 * verification column says in words whether the underlying page was read.
 */
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { market as marketApi } from "../../api/client";
import type { MarketPreview, MarketRow, MarketSearchResult } from "../../api/client";
import type { EgressState, MarketFinding, PublicMarketQuery } from "../../types/analysis";

const VERIFICATION: Record<string, string> = {
  source_read: "source read",
  snippet_only: "snippet only",
  source_not_verified: "source not verified",
};

/** The backend's own word for how a row was checked, in words - and the raw
 *  value when it is a word this build does not know. Never a guess, and never
 *  blank: a missing verification column reads as "verified". */
function verificationWords(v: string): string {
  return VERIFICATION[v] ?? v;
}

// ------------------------------------------------------------------ the copy
//
// Every sentence below is a claim this panel makes on its own behalf, so each
// one is a named constant: it is asserted by name in the tests, and a reader
// changing one has to look at what it promises.

/** Preserved verbatim. It is the caption the offline build shipped with, and
 *  it is what an `enabled: false` search means too - the feature is off and
 *  every row is a fixture. */
const SAMPLE_BANNER_TAIL =
  "This machine is offline. Every row below is an illustrative sample and must not be described as live market data.";

/** The honest limit of the whole feature. Preserved verbatim. */
const PUBLIC_LIMIT =
  "Public web findings cannot prove internal project compliance. Snippets are preliminary evidence; the verification column says whether the page was read.";

/** Nothing safe survived scrubbing. Says plainly that no search is possible,
 *  and refuses the obvious bad offer - sending the raw text anyway - before
 *  the reader can ask for it. */
const NO_SAFE_PHRASE =
  "No safe search phrase could be formed from what you typed, so no search is possible. The text you typed will not be sent in its place, and nothing has been sent.";

/** The preview is a read on this machine. If it cannot be read, the payload
 *  cannot be shown, and this panel does not send what it cannot show. */
const PREVIEW_UNREACHABLE =
  "The backend could not be reached, so the exact outbound payload cannot be shown here.";

/** Confirm was pressed while the payload was unknown. Nothing left. */
const NOTHING_SENT_UNSHOWN =
  "Nothing was sent. The exact outbound payload was never shown, and this panel does not send what it cannot show.";

/** Cancel's own promise, next to the button, so it does not have to be taken
 *  on trust. */
const CANCEL_SENDS_NOTHING = "Cancel closes this and sends nothing.";

/** The fallback, in one plain sentence. It names what did not happen ("did
 *  not answer") rather than what failed, because a tier returning nothing is
 *  not the same as a tier erroring, and the API does not distinguish them. */
const TIER_FALLBACK =
  "The general web search did not answer. The rows below come from reference sources: they are background only and are not market findings.";

/** Printed under a failure, so the absence of rows is stated rather than left
 *  to be noticed. */
const FAILURE_NO_ROWS = "No rows are shown, and no sample rows have been put in their place.";

/** An empty result is a real answer and is worded as one. */
const NO_RESULTS =
  "The search ran and found nothing. That is the answer: there are no public findings for this phrase.";

/** The search request itself did not get through. Nothing was searched and
 *  nothing stale is left on screen. */
const SEARCH_UNREACHABLE =
  "The backend could not be reached, so no search was made. Nothing is shown here.";

/** On every reference row. The row already prints its label; this says what
 *  the label MEANS for a reader deciding whether to rely on it. */
const REFERENCE_CAPTION =
  "Background only. This row is not a market finding and cannot evidence a market condition.";

const REFERENCE_LABEL = "reference - background only";

// ------------------------------------------------------------------- pieces

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

/** The provider label, printed as sent.
 *
 *  The reference tint is decoration; the label text is the carrier, and the
 *  row's own caption states the consequence in words. Colour alone would fail
 *  a reader who cannot see it, which is the reader this label exists for.
 */
function ProviderTag({ label }: { label: string }) {
  const isReference = label === REFERENCE_LABEL;
  return (
    <span
      className={[
        "rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
        isReference
          ? "border border-warn-500/70 bg-warn-500/10 text-warn-500"
          : "border border-signal-500/50 bg-signal-500/10 text-signal-400",
      ].join(" ")}
    >
      {label}
    </span>
  );
}

/** A legacy fixture row, off the `findings` prop. Unchanged. */
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
        <dd className="text-slateish-300">{verificationWords(f.verification)}</dd>
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

/**
 * A row from /api/market/search.
 *
 * `published` null withholds the label with the value. `provider_label` is
 * always drawn. A reference row gets a warn-tinted label AND its own
 * sentence: the two together are what stop it being read as a market finding
 * by someone skimming, and the sentence is what survives a greyscale print.
 *
 * No <a> anywhere. A url on this screen is evidence of where a claim came
 * from, not an invitation to leave the machine, and a sample row's
 * `sample://` url must stay unclickable by construction.
 */
function SearchRow({ row }: { row: MarketRow }) {
  const isReference = row.provider_label === REFERENCE_LABEL;
  return (
    <li
      className={[
        "border-t border-ink-700/60 py-2.5 first:border-t-0",
        isReference ? "border-l-2 border-l-warn-500/60 pl-3" : "",
      ].join(" ")}
    >
      <div className="flex flex-wrap items-baseline gap-2">
        {row.is_sample && <SampleTag />}
        <ProviderTag label={row.provider_label} />
        <p className="model-prose text-sm text-slateish-200">{row.text}</p>
      </div>
      {isReference && <p className="mt-1 text-xs text-warn-500">{REFERENCE_CAPTION}</p>}
      <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        <dt className="text-slateish-500">publisher</dt>
        <dd className="text-slateish-300">{row.publisher}</dd>
        {/* A null `published` withholds the LABEL as well as the value. The
            label over an empty cell is the "N/A" defect wearing a different
            hat: it asserts that a date was reported and then hidden. */}
        {row.published !== null && (
          <>
            <dt className="text-slateish-500">published</dt>
            <dd className="text-slateish-300">{row.published}</dd>
          </>
        )}
        <dt className="text-slateish-500">retrieved</dt>
        <dd className="text-slateish-300">{row.retrieved}</dd>
        <dt className="text-slateish-500">verification</dt>
        <dd className="text-slateish-300">{verificationWords(row.verification)}</dd>
        <dt className="text-slateish-500">url</dt>
        <dd>
          <code className="break-all font-mono text-[11px] text-slateish-400">{row.url}</code>
        </dd>
      </dl>
    </li>
  );
}

/** Attempted against answered, and the fallback sentence when the answered set
 *  is the narrower one. An empty attempted list prints NOTHING - a heading
 *  over no tiers is a label over nothing. */
function TierTrail({ result }: { result: MarketSearchResult }) {
  const attempted = result.tiers_attempted;
  const answered = result.tiers_answered;
  if (attempted.length === 0 && answered.length === 0) return null;
  const silent = attempted.filter((t) => !answered.includes(t));
  const narrower = silent.length > 0 && answered.length > 0;
  return (
    <div className="mt-2 space-y-1 border-t border-ink-700 pt-2 text-xs">
      {attempted.length > 0 && (
        <p className="text-slateish-400">Tiers attempted: {attempted.join(", ")}</p>
      )}
      {answered.length > 0 && (
        <p className="text-slateish-400">Tiers that answered: {answered.join(", ")}</p>
      )}
      {silent.length > 0 && (
        <p className="text-slateish-400">Tried and did not answer: {silent.join(", ")}</p>
      )}
      {narrower && <p className="text-warn-500">{TIER_FALLBACK}</p>}
    </div>
  );
}

// -------------------------------------------------------------- the form

/**
 * The query form.
 *
 * `onSubmit` OPENS THE PREVIEW. That is the whole point of the keyboard path:
 * Enter in the field is the same action as the button, and neither of them can
 * send. Nothing here is debounced, and there is no blur handler - a reader who
 * tabs out of a half-typed phrase has not asked for anything to happen.
 */
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

// ----------------------------------------------------------------- preview

type PreviewState =
  | { s: "loading" }
  | { s: "ready"; data: MarketPreview }
  | { s: "unreachable" }
  | { s: "error"; message: string };

/** The two scope values this PANEL adds to the phrase, said out loud.
 *
 *  /api/market/preview takes the phrase alone, so `preview.payload` cannot
 *  attest to them. Rather than let the dialog imply that the payload is the
 *  whole request, they are listed separately and attributed to this panel.
 *  Withheld entirely when neither is set - there is nothing to disclose. */
function scopeLine(q: PublicMarketQuery): string | null {
  const parts: string[] = [];
  if (q.country !== null) parts.push(`country ${q.country}`);
  if (q.freshness_days !== null) parts.push(`freshness ${q.freshness_days} days`);
  return parts.length === 0 ? null : parts.join(", ");
}

function ConfirmDialog({
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
  const blocked = egress.allow_public_egress === false;
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

  const scope = scopeLine(query);

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

        {/* What the reader typed, before any scrubbing, so the two strings can
            be compared side by side. This one is the reader's own and is
            always available; the one below is the backend's. */}
        <p className="mt-3 text-[11px] uppercase tracking-wider text-slateish-500">What you typed</p>
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
            <p className="mt-3 text-[11px] uppercase tracking-wider text-slateish-500">
              The phrase that would be sent
            </p>
            <p className="mt-1 break-words text-sm text-slateish-100">{preview.data.phrase}</p>
            <p className="mt-3 text-[11px] uppercase tracking-wider text-slateish-500">
              The exact outbound payload, as the backend states it
            </p>
            <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all rounded border border-ink-600 bg-ink-900 p-3 font-mono text-xs text-slateish-100">
              {JSON.stringify(preview.data.payload, null, 2)}
            </pre>
            {scope !== null && (
              <p className="mt-2 text-xs text-slateish-400">
                Sent with it by this panel: {scope}.
              </p>
            )}
            {preview.data.tiers_configured.length > 0 && (
              <p className="mt-2 text-xs text-slateish-400">
                Would be asked of: {preview.data.tiers_configured.join(", ")}.
              </p>
            )}
          </>
          )}
        </div>

        {blocked && (
          <p role="status" className="mt-2 text-xs text-warn-500">
            Public egress is blocked in this build.
          </p>
        )}

        <p className="mt-3 text-xs text-slateish-400">{CANCEL_SENDS_NOTHING}</p>

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
            onClick={onSend}
            disabled={blocked || noSafePhrase}
            aria-disabled={blocked || noSafePhrase}
            title={
              blocked
                ? "Public egress is blocked in this build."
                : noSafePhrase
                  ? NO_SAFE_PHRASE
                  : undefined
            }
            className="rounded border border-signal-500/60 px-3 py-1.5 text-sm text-signal-300 hover:bg-signal-500/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Confirm and send
          </button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ results

type SearchState =
  | { s: "idle" }
  | { s: "running" }
  | { s: "ready"; data: MarketSearchResult }
  | { s: "unreachable" }
  | { s: "error"; message: string }
  | { s: "not_sent" };

function SampleBanner() {
  return (
    <div role="note" className="mt-3 rounded border-2 border-warn-500/70 bg-warn-500/10 px-3 py-2 text-sm text-warn-500">
      <span className="font-semibold">SAMPLE DATA &mdash; NOT LIVE.</span> {SAMPLE_BANNER_TAIL}
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
function SearchOutcome({ result }: { result: MarketSearchResult }) {
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
        <SampleBanner />
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
  /** The dialog this panel opened itself. The `pendingQuery` prop is the
   *  parent-controlled path (AnalysisModeScreen holds it in state); both are
   *  honoured and both are cleared on every close, so there is only ever one
   *  dialog and it cannot outlive either owner. */
  const [pendingLocal, setPendingLocal] = useState<PublicMarketQuery | null>(null);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [search, setSearch] = useState<SearchState>({ s: "idle" });

  const pending = pendingLocal ?? pendingQuery ?? null;
  const phrase = pending === null ? null : pending.query;

  // The preview is a read on this machine's own backend and performs no
  // egress, so it is safe to run the moment the dialog opens. It is keyed on
  // the phrase alone: reopening the dialog on the same phrase re-reads it
  // rather than trusting a value the scrubber may since have been
  // reconfigured for.
  useEffect(() => {
    if (phrase === null) {
      setPreview(null);
      return;
    }
    let live = true;
    setPreview({ s: "loading" });
    void marketApi.preview(phrase).then((r) => {
      if (!live) return;
      if (r.ok) {
        setPreview({ s: "ready", data: r.data });
      } else if (r.disconnected) {
        setPreview({ s: "unreachable" });
      } else {
        setPreview({ s: "error", message: r.error.message });
      }
    });
    return () => {
      live = false;
    };
  }, [phrase]);

  const close = useCallback(() => {
    setPendingLocal(null);
    setPreview(null);
  }, []);

  function openPreview(q: PublicMarketQuery) {
    // Both owners, so the parent's own messaging still works and the dialog
    // opens even when no parent is listening.
    setPendingLocal(q);
    onPreviewQuery?.(q);
  }

  function cancel() {
    close();
    onCancelQuery?.();
  }

  /**
   * The one path that can leave the machine, and the only caller of
   * `market.search` in this file.
   *
   * It sends ONLY what was shown: a preview that is ready with a non-null
   * phrase. In every other state it sends nothing and says so - see the note
   * at the top of this file for why the button is live rather than disabled
   * there.
   */
  function send() {
    const approved = preview !== null && preview.s === "ready" ? preview.data.phrase : null;
    const q = pending;
    close();
    onConfirmQuery?.();
    if (approved === null || q === null) {
      setSearch({ s: "not_sent" });
      return;
    }
    setSearch({ s: "running" });
    void marketApi
      .search({ phrase: approved, country: q.country, freshness_days: q.freshness_days })
      .then((r) => {
        // A failed request replaces the state outright. There is no branch
        // that leaves the previous result, or the sample rows, on screen.
        if (r.ok) setSearch({ s: "ready", data: r.data });
        else if (r.disconnected) setSearch({ s: "unreachable" });
        else setSearch({ s: "error", message: r.error.message });
      });
  }

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

      <div aria-live="polite">
        {search.s === "idle" && (
          <>
            <SampleBanner />
            {findings.length === 0 ? (
              <p className="mt-3 text-sm text-slateish-500">No market sample loaded.</p>
            ) : (
              <ul className="mt-3">
                {findings.map((f, i) => (
                  <FindingRow key={`${f.url}-${i}`} f={f} />
                ))}
              </ul>
            )}
          </>
        )}

        {search.s === "running" && (
          <p role="status" className="mt-3 text-sm text-slateish-300">
            Searching public sources&hellip;
          </p>
        )}

        {search.s === "not_sent" && <p className="mt-3 text-sm text-warn-500">{NOTHING_SENT_UNSHOWN}</p>}

        {search.s === "unreachable" && (
          <p className="mt-3 text-sm text-danger-500">{SEARCH_UNREACHABLE}</p>
        )}

        {search.s === "error" && <p className="mt-3 text-sm text-danger-500">{search.message}</p>}

        {search.s === "ready" && <SearchOutcome result={search.data} />}
      </div>

      <p className="mt-3 border-t border-ink-700 pt-2 text-xs text-slateish-500">{PUBLIC_LIMIT}</p>

      <QueryForm onPreview={openPreview} />

      {pending !== null && (
        <ConfirmDialog
          query={pending}
          egress={egress}
          preview={preview ?? { s: "loading" }}
          onSend={send}
          onCancel={cancel}
        />
      )}
    </section>
  );
}
