import { useCallback, useEffect, useRef, useState } from "react";

import { type EngineChoice, type PointsListing, type ReviewPlan, pageV2Switch, reviewPoints } from "../../../api/reviewPoints";

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
    add: (body: Parameters<typeof reviewPoints.add>[1]) => write(() => reviewPoints.add(documentId ?? "", body)),
  };
}

/** The plan for one engine choice, read again when the choice (or the paper) changes. Reading it changes nothing on the server. */
export function usePlan(documentId: string | null, engine: EngineChoice) {
  const [plan, setPlan] = useState<Loaded<ReviewPlan>>({ state: "loading" });
  const reload = useCallback(async () => {
    if (!documentId) return;
    const r = await reviewPoints.plan(documentId, engine);
    setPlan(r.ok ? { state: "ok", data: r.data } : { state: "error", message: r.error.message });
  }, [documentId, engine]);
  useEffect(() => { setPlan({ state: "loading" }); void reload(); }, [reload]);
  return { plan, reload };
}
