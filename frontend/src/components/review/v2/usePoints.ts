import { useCallback, useEffect, useRef, useState } from "react";

import { type EngineChoice, type PointsListing, type ReviewPlan, oldCrsDownloadOffered, pageV2Switch, reviewPoints } from "../../../api/reviewPoints";

/** The redesigned page's switch, read once. False while unknown: the old page stays. */
export function usePageV2Switch(): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    let live = true;
    void pageV2Switch().then((v) => { if (live) setOn(v); });
    return () => { live = false; };
  }, []);
  return on;
}

/** Owner order, 16 Nov 2026: whether the older per-review CRS files (no count line) are offered, read once. True until the server
 *  says otherwise, as before; the server is the gate. */
export function useOldCrsDownload(): boolean {
  const [on, setOn] = useState(true);
  useEffect(() => {
    let live = true;
    void oldCrsDownloadOffered().then((v) => { if (live) setOn(v); });
    return () => { live = false; };
  }, []);
  return on;
}

export type Loaded<T> = { state: "loading" } | { state: "error"; message: string } | { state: "ok"; data: T };

/** The paper's list of points, read again after every write (the server answers each write with the new list). */
export function usePoints(documentId: string | null) {
  const [listing, setListing] = useState<Loaded<PointsListing>>({ state: "loading" });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const reload = useCallback(async () => {
    if (!documentId) return;
    const r = await reviewPoints.list(documentId);
    if (!alive.current) return;
    setListing(r.ok ? { state: "ok", data: r.data } : { state: "error", message: r.error.message });
  }, [documentId]);
  useEffect(() => { setListing({ state: "loading" }); void reload(); }, [reload]);

  const write = useCallback(async (call: () => ReturnType<typeof reviewPoints.decide>) => {
    setBusy(true); setProblem(null);
    const r = await call();
    if (!alive.current) return false;
    setBusy(false);
    if (!r.ok) { setProblem(r.error.message); return false; }
    setListing({ state: "ok", data: r.data });
    return true;
  }, []);

  return {
    listing, busy, problem, reload,
    decide: (body: Parameters<typeof reviewPoints.decide>[1]) => write(() => reviewPoints.decide(documentId ?? "", body)),
    keepAll: (ids: string[]) => write(() => reviewPoints.keepAll(documentId ?? "", ids)),
    confirmNa: (ids: string[]) => write(() => reviewPoints.confirmNotApplicable(documentId ?? "", ids)),
    undoNa: (id: string) => write(() => reviewPoints.undoNotApplicable(documentId ?? "", id)),
    add: (body: Parameters<typeof reviewPoints.add>[1]) => write(() => reviewPoints.add(documentId ?? "", body)),
  };
}

/** The plan for one engine choice, read again when the choice (or the paper) changes. Reading it changes nothing on the server. */
const PLAN_SLOW_MS = 45_000;
export function usePlan(documentId: string | null, engine: EngineChoice, ticked: string[] = [], slowMs = PLAN_SLOW_MS) {
  const [plan, setPlan] = useState<Loaded<ReviewPlan>>({ state: "loading" });
  /** The choice the plan on screen was read for. A plan is used only for the choice on screen. */
  const [forEngine, setForEngine] = useState<EngineChoice | null>(null);
  const [forDocument, setForDocument] = useState<string | null>(null);
  const latest = useRef(0);
  const reload = useCallback(async () => {
    if (!documentId) return;
    const mine = ++latest.current;
    // A plan that has not answered in a minute is said so (it never stays "checking"); a late answer still replaces this.
    const slow = setTimeout(() => {
      if (mine === latest.current) { setForEngine(engine); setPlan((p) => (p.state === "loading" ? { state: "error", message: "Checking what this would do is taking too long. Try again in a moment." } : p)); }
    }, slowMs);
    const r = await reviewPoints.plan(documentId, engine, ...(ticked.length ? [ticked] : []));
    clearTimeout(slow);
    // OUT-OF-ORDER ANSWERS: a plan that is not the answer to the LAST request (an earlier choice answering late) is ignored.
    if (mine !== latest.current) return;
    setForEngine(engine);
    setForDocument(documentId);
    setPlan(r.ok ? { state: "ok", data: r.data } : { state: "error", message: r.error.message });
  }, [documentId, engine, ticked.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setPlan({ state: "loading" }); setForEngine(null); void reload(); }, [reload]);
  useEffect(() => () => { latest.current += 1; }, []);
  // The plan on screen is used only for the choice on screen: in the render between a changed choice and the effect that clears the
  // old plan, nothing is offered (Review is disabled, no list is shown).
  const masked: Loaded<ReviewPlan> = forEngine === engine && forDocument === documentId ? plan : { state: "loading" };
  return { plan: masked, reload, forEngine };
}
