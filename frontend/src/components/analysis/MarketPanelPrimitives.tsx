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
 * AND IT DOES NOT SEND WHAT IT CANNOT SHOW. The payloads in the dialog are
 * the BACKEND'S (`preview.payloads`), not a client-side re-serialisation of
 * the form: a reconstruction is a guess at what leaves the machine, and a
 * guess that has drifted is a lie told with confidence. So when the preview
 * has not arrived, Confirm sends nothing at all and the panel says so.
 *
 * ONE PAYLOAD PER TIER, ALL OF THEM RENDERED. A search builds one payload per
 * configured tier and sends every one, so a dialog showing a single object
 * would have the reader approve one request while three left. This is not
 * hypothetical: the backend once returned a single `payload` for the
 * reference tier with no country and no freshness while a search sent one per
 * tier carrying both - and because these types lived in api/client.ts rather
 * than contracts/types.ts, the rename to `payloads` compiled, all tests
 * passed, and this dialog rendered `undefined` in the one place it exists to
 * fill. The types now live in the contract, so that drift is a compile error.
 *
 * THE SCOPE IS IN THE PAYLOADS, not in a footnote. `country` and
 * `freshness_days` are passed to /api/market/preview and come back inside
 * each payload, stated by the backend. This panel used to list them itself
 * and attribute them to itself, which asked the reader to trust the panel
 * about what the request contained. The button is
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
import type { MarketRow, MarketSearchResult } from "../../api/client";
import type { EgressState, MarketFinding } from "../../types/analysis";

const VERIFICATION: Record<string, string> = {
  source_read: "source read",
  snippet_only: "snippet only",
  source_not_verified: "source not verified",
};

/** The backend's own word for how a row was checked, in words - and the raw
 *  value when it is a word this build does not know. Never a guess, and never
 *  blank: a missing verification column reads as "verified". */
export function verificationWords(v: string): string {
  return VERIFICATION[v] ?? v;
}

// ------------------------------------------------------------------ the copy
//
// Every sentence below is a claim this panel makes on its own behalf, so each
// one is a named constant: it is asserted by name in the tests, and a reader
// changing one has to look at what it promises.

/** The half of the sample caption that is true in every state: these rows are
 *  fixtures. The REASON they are fixtures is not - it depends on the two
 *  egress flags - so it is computed by `sampleReason` and prepended.
 *
 *  This constant used to open with a claim that the machine had no network. It
 *  was a literal, so it kept making that claim with both flags on and a live
 *  lane behind it. ADR-0002 forbids the sentence outright: this is a
 *  locally-inferencing system on a NETWORKED machine, and calling it
 *  air-gapped is a false security claim about the one property the product is
 *  sold on. The claim is gone from this file; the egress flags are the only
 *  thing that may say what the posture is. */
export const SAMPLE_BANNER_TAIL =
  "Every row below is an illustrative sample and must not be described as live market data.";

/** Why the rows on screen are samples, in the reader's terms, from the same
 *  two flags the backend gates the request on. Never asserts a posture the
 *  flags do not carry - with both flags on and nothing searched yet, the
 *  honest answer is that no search has been run, not a claim about the
 *  network. */
export const NO_SEARCH_YET = "No search has been run yet.";

export function sampleReason(egress: EgressState): string {
  const webOff = egress.web_search_enabled === false;
  const egressOff = egress.allow_public_egress === false;
  if (webOff && egressOff) return "Web search and public egress are both off in this build.";
  if (webOff) return "Web search is off in this build.";
  if (egressOff) return "Public egress is blocked in this build.";
  return NO_SEARCH_YET;
}

/** The same question, asked about a search that HAS run and came back
 *  `enabled: false`.
 *
 *  The two can disagree: the flags this screen was handed say live and the
 *  response says the feature is off. That is a real state - the screen reads
 *  `/api/analysis/...`'s egress block while the request is gated inside
 *  `market_transport` - and the honest thing is to report what the backend
 *  said rather than to print "no search has been run" over a search that was
 *  run, or to assert a posture from flags the request did not obey. */
export function searchDisabledReason(egress: EgressState): string {
  const reason = sampleReason(egress);
  return reason === NO_SEARCH_YET
    ? "The backend reported that public search is off in this build."
    : reason;
}

/** The honest limit of the whole feature. Preserved verbatim. */
export const PUBLIC_LIMIT =
  "Public web findings cannot prove internal project compliance. Snippets are preliminary evidence; the verification column says whether the page was read.";

/** Nothing safe survived scrubbing. Says plainly that no search is possible,
 *  and refuses the obvious bad offer - sending the raw text anyway - before
 *  the reader can ask for it. */
export const NO_SAFE_PHRASE =
  "No safe search phrase could be formed from what you typed, so no search is possible. The text you typed will not be sent in its place, and nothing has been sent.";

/** The preview is a read on this machine. If it cannot be read, the payload
 *  cannot be shown, and this panel does not send what it cannot show. */
export const PREVIEW_UNREACHABLE =
  "The backend could not be reached, so the exact outbound payload cannot be shown here.";

/** Confirm was pressed while the payload was unknown. Nothing left. */
export const NOTHING_SENT_UNSHOWN =
  "Nothing was sent. The exact outbound payload was never shown, and this panel does not send what it cannot show.";

/** Cancel's own promise, next to the button, so it does not have to be taken
 *  on trust. */
export const CANCEL_SENDS_NOTHING = "Cancel closes this and sends nothing.";

/** The fallback, in one plain sentence. It names what did not happen ("did
 *  not answer") rather than what failed, because a tier returning nothing is
 *  not the same as a tier erroring, and the API does not distinguish them. */
export const TIER_FALLBACK =
  "One or more public sources did not answer. Any rows shown are labeled with their actual source tier; they are preliminary background evidence, not proof of internal project compliance.";

/** Printed under a failure, so the absence of rows is stated rather than left
 *  to be noticed. */
export const FAILURE_NO_ROWS = "No rows are shown, and no sample rows have been put in their place.";

/** An empty result is a real answer and is worded as one. */
export const NO_RESULTS =
  "The search ran and found nothing. That is the answer: there are no public findings for this phrase.";

/** The search request itself did not get through. Nothing was searched and
 *  nothing stale is left on screen. */
export const SEARCH_UNREACHABLE =
  "The backend could not be reached, so no search was made. Nothing is shown here.";

/** On every reference row. The row already prints its label; this says what
 *  the label MEANS for a reader deciding whether to rely on it. */
export const REFERENCE_CAPTION =
  "Background only. This row is not a market finding and cannot evidence a market condition.";

export const REFERENCE_LABEL = "reference - background only";

// ------------------------------------------------------------------- pieces

export function SampleTag() {
  return (
    <span className="rounded-[var(--radius-xs)] border border-ink-500 px-1 font-mono text-xs uppercase tracking-wider text-slateish-400">
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
export function ProviderTag({ label }: { label: string }) {
  const isReference = label === REFERENCE_LABEL;
  return (
    <span
      className={[
        "rounded-[var(--radius-xs)] px-1.5 py-0.5 font-mono text-xs uppercase tracking-wider",
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
export function FindingRow({ f }: { f: MarketFinding }) {
  return (
    <li className="border-t border-ink-700/60 py-2.5 first:border-t-0">
      <div className="flex flex-wrap items-baseline gap-2">
        <SampleTag />
        <p className="model-prose text-sm text-slateish-200">{f.claim}</p>
      </div>
      <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        <dt className="text-slateish-500">publisher</dt>
        <dd className="text-slateish-300">{f.publisher}</dd>
        {/* RULE 1: null renders as NOTHING. A dash reads like a measurement -
            "reported and withheld" rather than "no date". `SearchRow` already
            withholds the pair; this row printed the dash. */}
        {f.published_at !== null && (
          <>
            <dt className="text-slateish-500">published</dt>
            <dd className="text-slateish-300">{f.published_at}</dd>
          </>
        )}
        <dt className="text-slateish-500">retrieved</dt>
        <dd className="text-slateish-300">{f.retrieved_at}</dd>
        <dt className="text-slateish-500">verification</dt>
        <dd className="text-slateish-300">{verificationWords(f.verification)}</dd>
        <dt className="text-slateish-500">url</dt>
        <dd>
          <code
            title="sample row; this link was not followed"
            className="break-all font-mono text-xs text-slateish-400"
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
export function SearchRow({ row }: { row: MarketRow }) {
  const isReference = row.provider_label === REFERENCE_LABEL;
  return (
    <li
      className={[
        "border-t border-ink-700/60 py-2.5 first:border-t-0",
        isReference ? "border-l-2 border-l-warn-500/60 ps-3" : "",
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
          <code className="break-all font-mono text-xs text-slateish-400">{row.url}</code>
        </dd>
      </dl>
    </li>
  );
}

/** Attempted against answered, and the fallback sentence when the answered set
 *  is the narrower one. An empty attempted list prints NOTHING - a heading
 *  over no tiers is a label over nothing. */
export function TierTrail({ result }: { result: MarketSearchResult }) {
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
