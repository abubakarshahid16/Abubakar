/**
 * Container for MarketPanel: owns the two API calls, hands the panel its props.
 *
 * The banner text comes from the API's `egress` object rather than being
 * hard-coded here, so a build that ever enables egress cannot leave a screen
 * saying "web search off" while it is on.
 *
 * A failed load renders NO findings rather than an empty panel with a
 * reassuring banner: "no market findings" reads as a measurement, and this
 * build has not measured anything.
 */
import { useCallback, useEffect, useState } from "react";

import { market as marketApi } from "../api/client";
import { MarketPanel } from "../components/analysis/MarketPanel";
import type { EgressState, MarketFinding, MarketQueryRequest } from "../types/api";

const BLOCKED: EgressState = { web_search_enabled: false, allow_public_egress: false };

export function MarketScreen() {
  const [findings, setFindings] = useState<MarketFinding[]>([]);
  const [egress, setEgress] = useState<EgressState>(BLOCKED);
  const [pending, setPending] = useState<MarketQueryRequest | null>(null);

  const load = useCallback(async () => {
    const r = await marketApi.findings();
    if (r.ok) {
      setFindings(r.data.findings);
      setEgress(r.data.egress);
    }
    // On failure the state stays empty and blocked. Defaulting to "egress
    // allowed" on an unreadable response would be the wrong direction to fail.
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const preview = useCallback((q: MarketQueryRequest) => setPending(q), []);

  const confirm = useCallback(async () => {
    if (!pending) return;
    // Still a preview. The route builds the object and does not send it, and
    // the response says so; this exists so the shape of a confirmation step
    // can be reviewed before there is anything to confirm.
    await marketApi.previewQuery(pending);
    setPending(null);
  }, [pending]);

  return (
    <MarketPanel
      findings={findings}
      egress={egress}
      onPreviewQuery={preview}
      pendingQuery={pending}
      onConfirmQuery={confirm}
      onCancelQuery={() => setPending(null)}
    />
  );
}
