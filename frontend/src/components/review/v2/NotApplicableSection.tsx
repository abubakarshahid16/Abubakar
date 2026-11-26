/** Owner's decision on PR #1872: the lines the AI thinks do not apply (no proof found by code) are NOT the main questions. They are this
 *  short section, grouped by rule book, each line with a tick (one engineer decision, recorded with who and when; unticking undoes it)
 *  and "Confirm all" for the open lines (the same tick on each). A ticked line reads "Does not apply (confirmed by the engineer)". */
import { useMemo } from "react";

import type { PointsListing, ReviewPoint } from "../../../api/reviewPoints";
import { Button } from "../../kit/Kit";

export const NA_TITLE = "AI thinks these do not apply, tick to confirm";
const NO_BOOK_GROUP = "No rule book named";

function groups(points: ReviewPoint[]): [string, ReviewPoint[]][] {
  const out = new Map<string, ReviewPoint[]>();
  for (const p of points) {
    const key = p.rule_book ?? NO_BOOK_GROUP;
    out.set(key, [...(out.get(key) ?? []), p]);
  }
  return [...out.entries()];
}

export function NotApplicableSection({ points, counts, confirm, undo, busy }: {
  points: ReviewPoint[]; counts: PointsListing["counts"]["not_applicable_to_confirm"];
  confirm: (ids: string[]) => Promise<boolean>; undo: (id: string) => Promise<boolean>; busy: boolean;
}) {
  const grouped = useMemo(() => groups(points), [points]);
  if (!points.length) return null;
  const open = points.filter((p) => p.decision.state !== "keep");
  return (
    <section data-testid="v2-na-section" aria-labelledby="v2-na-title" className="space-y-2 rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="v2-na-title" className="text-sm font-semibold text-slateish-100">{NA_TITLE}</h2>
        <Button variant="secondary" size="sm" disabled={busy || open.length === 0} onClick={() => void confirm(open.map((p) => p.id))}>Confirm all</Button>
      </div>
      {counts?.sentence && <p data-testid="v2-na-count" className="text-xs text-slateish-400">{counts.sentence}</p>}
      {grouped.map(([book, ps]) => (
        <div key={book} data-testid="v2-na-group" className="space-y-1">
          <p className="text-xs font-semibold text-slateish-300">{book} ({ps.length})</p>
          <ul className="space-y-1">
            {ps.map((p) => {
              const ticked = p.decision.state === "keep";
              return (
                <li key={p.id} data-testid="v2-na-line" className="flex items-start gap-2 text-sm">
                  <input type="checkbox" checked={ticked} disabled={busy} aria-label={`Confirm: ${p.name} does not apply`}
                    onChange={() => void (ticked ? undo(p.id) : confirm([p.id]))} className="mt-1" />
                  <span className="flex-1">
                    <span className="text-slateish-100">{p.name}</span>
                    {p.clause && <span className="text-xs text-slateish-400"> · clause {p.clause}</span>}
                    {p.page != null && <span className="text-xs text-slateish-400"> · page {p.page}</span>}
                    <span className="block text-xs text-slateish-400">
                      {ticked ? `${p.decision.words}${p.decision.by ? ` · ${p.decision.by}` : ""}` : `${p.ai_label ?? p.pill} · not confirmed yet`}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </section>
  );
}
