import { useCallback, useEffect, useRef, useState } from "react";

import { type GeneralReview, generalReview } from "../../../api/generalReview";

/** "none": the paper has no general review (the server's 404, which is also what a paper outside the reader's access answers). */
export type GeneralState = { state: "loading" } | { state: "none" } | { state: "error"; message: string } | { state: "ok"; data: GeneralReview };

/** The paper's general review, read once per paper: the one OPENED when `runId` names a general run of it (lead-4, 26 Nov 2026: the
 *  row and its Open named the signed Claude review while the page drew the paper's newer local rough draft), else the latest. While it
 *  is unknown or absent the older page is drawn. */
export function useGeneralReview(documentId: string | null, runId: string | null = null): { general: GeneralState; method: "general" | "earlier" | null; reload: () => Promise<void> } {
  const [general, setGeneral] = useState<GeneralState>({ state: "loading" });
  const [method, setMethod] = useState<"general" | "earlier" | null>(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const reload = useCallback(async () => {
    if (!documentId) { setGeneral({ state: "none" }); return; }
    const r = runId ? await generalReview.get(documentId, runId) : await generalReview.get(documentId);
    if (!alive.current) return;
    if (r.ok) setGeneral({ state: "ok", data: r.data });
    else if (!r.disconnected && r.error.code === "not_found") setGeneral({ state: "none" });
    else setGeneral({ state: "error", message: r.error.message });
  }, [documentId, runId]);
  useEffect(() => { setGeneral({ state: "loading" }); void reload(); }, [reload]);
  useEffect(() => {
    let live = true;
    void generalReview.method().then((r) => { if (live) setMethod(r.ok ? r.data.method : null); });
    return () => { live = false; };
  }, []);
  return { general, method, reload };
}

/** True when the page should draw the general results: the latest finished review of the paper is a general one. */
export function latestGeneral(g: GeneralState): GeneralReview | null {
  return g.state === "ok" && g.data.is_latest !== false ? g.data : null;
}
