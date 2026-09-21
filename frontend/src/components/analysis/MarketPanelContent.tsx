import { useCallback, useEffect, useState } from "react";
import { market as marketApi } from "../../api/client";
import type { MarketFinding, PublicMarketQuery, EgressState } from "../../types/analysis";
import { QueryForm, ConfirmDialog, SearchOutcome } from "./MarketPanelDialogs";
import type { PreviewState, SearchState } from "./MarketPanelDialogs";
import { FindingRow, PUBLIC_LIMIT, SEARCH_UNREACHABLE, NOTHING_SENT_UNSHOWN } from "./MarketPanelPrimitives";
import { sampleReason } from "./MarketPanelPrimitives";
import { SampleBanner } from "./MarketPanelDialogs";
import { MarketPill } from "./MarketPill";

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
  // Hoisted out of the effect so they can be DEPENDENCIES of it. Read inside
  // the effect body instead, they would go stale: the effect keyed on the
  // phrase alone, so changing the country and reopening on the same phrase
  // would have previewed the old scope and then sent the new one - the
  // preview-is-not-the-payload defect again, in the panel this time.
  const pendingCountry = pending?.country ?? null;
  const pendingFreshness = pending?.freshness_days ?? null;

  // The preview is a read on this machine's own backend and performs no
  // egress, so it is safe to run the moment the dialog opens. It is keyed on
  // the phrase AND both scope fields: reopening on the same phrase re-reads
  // it rather than trusting a value the scrubber may since have been
  // reconfigured for, and a changed country re-reads it because the country
  // is inside the payload being approved.
  useEffect(() => {
    if (phrase === null) {
      setPreview(null);
      return;
    }
    let live = true;
    setPreview({ s: "loading" });
    // THE SCOPE GOES WITH IT. Both fields end up inside every payload the
    // backend returns, so the dialog shows the real request rather than the
    // phrase plus a footnote from this panel about what else was attached.
    void marketApi
      .preview(phrase, { country: pendingCountry, freshness_days: pendingFreshness })
      .then((r) => {
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
  }, [phrase, pendingCountry, pendingFreshness]);

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
    <section aria-label="Public market information" className="card-3d surface-card rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slateish-300">
          Public market information
        </h3>
        <div className="flex flex-wrap gap-1.5" aria-live="polite">
          {egress.web_search_enabled === false && <MarketPill>Web search off</MarketPill>}
          {egress.allow_public_egress === false && <MarketPill>Public egress blocked</MarketPill>}
        </div>
      </div>

      <div aria-live="polite">
        {search.s === "idle" && (
          <>
            <SampleBanner reason={sampleReason(egress)} />
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

        {search.s === "ready" && <SearchOutcome result={search.data} egress={egress} />}
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
