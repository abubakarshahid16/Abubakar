/**
 * Per-document classification, fetched once per document id.
 *
 * `GET /api/documents` does NOT carry a document's type - the register axis
 * lives on `/documents/{id}/classification`, one call per document. There is
 * no bulk route today, so this hook is the ONE place that fans a list of ids
 * out into N requests. When a bulk endpoint exists, this is the only file
 * that changes; nothing that calls the hook needs to know how the answer was
 * fetched.
 *
 * BOUNDED, not one `Promise.all` over the whole corpus: `MAX_CONCURRENT`
 * caps how many requests are in flight at once, so a much larger corpus than
 * today's ~17 documents does not open dozens of sockets the moment the
 * screen mounts.
 *
 * Refetches only ids it has not already resolved. Without that guard, every
 * poll tick (`usePoll` in DocumentsView) would re-fetch all seventeen
 * classifications on an idle screen, purely because the id array is a new
 * reference each render - and it would also clobber a classification this
 * screen just confirmed with the pre-confirm answer from a request that was
 * still in flight.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { classification } from "../../api/client";
import type { DocumentClassification } from "../../types/api";

const MAX_CONCURRENT = 6;

export interface DocumentClassifications {
  /** Present once that document's classification has answered. Absent (not
   *  `null`) while the request is in flight or has not been started yet -
   *  callers must not read a missing entry as "awaiting a type", which is a
   *  real answer the server gives, not a loading state. */
  byId: Record<string, DocumentClassification>;
  /** Patches one document's classification in place, e.g. after `confirm`
   *  returns - so the card updates instantly rather than waiting for the
   *  next poll to re-fetch it. */
  setOne: (id: string, next: DocumentClassification) => void;
  /** True once every requested document has either returned a classification
   *  or completed with an error. Callers can use this to avoid mounting a
   *  card in one group and immediately remounting it in another. */
  settled: boolean;
}

export function useDocumentClassifications(ids: string[]): DocumentClassifications {
  const [byId, setById] = useState<Record<string, DocumentClassification>>({});
  const [settledIds, setSettledIds] = useState<Set<string>>(() => new Set());
  // Read inside the effect without making the effect depend on the object
  // identity of `byId`, which changes on every confirm and would otherwise
  // re-trigger the fetch loop for ids that already have an answer.
  const byIdRef = useRef(byId);
  byIdRef.current = byId;
  const settledIdsRef = useRef(settledIds);
  settledIdsRef.current = settledIds;

  // Stable across renders that pass an equivalent but newly-allocated array -
  // the dependency below is this string, not `ids` itself.
  const idsKey = ids.join(",");

  useEffect(() => {
    let cancelled = false;
    const pending = ids.filter(
      (id) => !(id in byIdRef.current) && !settledIdsRef.current.has(id),
    );
    if (pending.length === 0) return;

    void (async () => {
      let cursor = 0;
      async function worker() {
        while (true) {
          const i = cursor++;
          if (i >= pending.length) return;
          const id = pending[i];
          const result = await classification.ofDocument(id);
          if (cancelled) return;
          if (result.ok) {
            setById((prev) => ({ ...prev, [id]: result.data }));
          }
          setSettledIds((prev) => {
            const next = new Set(prev);
            next.add(id);
            return next;
          });
          // A failed per-document fetch leaves that document simply
          // unanswered - the same "no filter/no chip is better than a wrong
          // one" rule the vocabulary hook follows - rather than surfacing a
          // per-card error for what is very often one flaky request.
        }
      }
      const workers = Array.from({ length: Math.min(MAX_CONCURRENT, pending.length) }, worker);
      await Promise.all(workers);
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey]);

  const setOne = useCallback((id: string, next: DocumentClassification) => {
    setById((prev) => ({ ...prev, [id]: next }));
    setSettledIds((prev) => {
      const updated = new Set(prev);
      updated.add(id);
      return updated;
    });
  }, []);

  return { byId, setOne, settled: ids.every((id) => settledIds.has(id)) };
}
