/** SPEC 8 and 9: the ONE list of points, worst first. Each row: a pill (what it is and how firm), a short plain name, the place, and
 *  Keep / Edit / Remove (a decided point shows its state). Repeated questions are grouped ("Question · 4 alike": Keep all / Open the 4).
 *  An opened point shows the action line and TWO BOXES side by side with ONLY code-verified text, and the "View page" link. */
import { useMemo, useState } from "react";

import type { ReviewPoint } from "../../../api/reviewPoints";
import { groupPlaceWords, placeWords, stateWords, tagsWords } from "./words";

type Decide = (body: { point_id: string; state: "keep" | "edit" | "remove"; text?: string; reason?: string }) => Promise<boolean>;

const PILL: Record<number, string> = {
  1: "fail", 2: "fail", 3: "fail", 4: "review", 5: "pass", 6: "pass", 7: "pass", 8: "cond",
};
function pillStyle(p: ReviewPoint) {
  const k = p.source === "added" ? "cond" : PILL[p.rank] ?? "cond";
  return { color: `var(--color-pill-${k}-fg)`, backgroundColor: `var(--color-pill-${k}-bg)`, borderColor: `var(--color-pill-${k}-border)` };
}

export function Pill({ p }: { p: ReviewPoint }) {
  return <span data-testid="v2-pill" style={pillStyle(p)} className="inline-block whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium">{p.pill}</span>;
}

function Boxes({ p, onViewPage }: { p: ReviewPoint; onViewPage: (documentId: string, page: number) => void }) {
  const box = "rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 p-3 text-sm";
  return (
    <div className="grid gap-3 md:grid-cols-2" data-testid="v2-boxes">
      <div className={box} data-testid="v2-paper-box">
        <p className="mb-1 text-xs font-semibold text-slateish-300">The paper{p.page != null ? `, page ${p.page}` : ""}</p>
        {p.paper_quote ? <blockquote className="text-slateish-100">{p.paper_quote}</blockquote> : null}
        <p className="mt-1 text-xs text-slateish-400">{p.paper_quote_note}</p>
        {p.view_page && (
          <button type="button" onClick={() => onViewPage(p.view_page!.document_id, p.view_page!.page)}
            className="mt-2 text-xs text-signal-300 underline-offset-2 hover:underline">View page</button>
        )}
      </div>
      <div className={box} data-testid="v2-clause-box">
        <p className="mb-1 text-xs font-semibold text-slateish-300">{p.rule_book ? `${p.rule_book}${p.clause ? `, clause ${p.clause}` : ""}` : "The rule"}</p>
        {p.clause_quote ? <blockquote className="text-slateish-100">{p.clause_quote}</blockquote> : null}
        <p className="mt-1 text-xs text-slateish-400">{p.clause_quote_note}</p>
      </div>
    </div>
  );
}

function Controls({ p, decide, busy }: { p: ReviewPoint; decide: Decide; busy: boolean }) {
  const [mode, setMode] = useState<"edit" | "remove" | null>(null);
  const [text, setText] = useState(p.action ?? "");
  const [reason, setReason] = useState("");
  const [again, setAgain] = useState(false);
  const decided = p.decision.state != null && !again;
  if (p.source === "added") return <span className="text-xs text-slateish-300">{stateWords(p)}</span>;
  if (decided) {
    return (
      <span className="flex items-center gap-2 text-xs text-slateish-300" data-testid="v2-state">
        {stateWords(p)}
        <button type="button" onClick={() => setAgain(true)} className="text-signal-300 underline-offset-2 hover:underline">Change</button>
      </span>
    );
  }
  const btn = "rounded-[var(--radius-sm)] border border-ink-500 px-2.5 py-1 text-xs text-slateish-100 hover:bg-ink-700 disabled:opacity-50";
  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <button type="button" className={btn} disabled={busy} onClick={() => void decide({ point_id: p.id, state: "keep" }).then(() => setAgain(false))}>Keep</button>
        <button type="button" className={btn} disabled={busy} onClick={() => setMode(mode === "edit" ? null : "edit")}>Edit</button>
        <button type="button" className={btn} disabled={busy} onClick={() => setMode(mode === "remove" ? null : "remove")}>Remove</button>
      </div>
      {mode === "edit" && (
        <div className="space-y-1">
          <textarea aria-label="Your wording" value={text} onChange={(e) => setText(e.target.value)} rows={3} className="w-full rounded border border-ink-500 bg-ink-900 p-2 text-sm text-slateish-100" />
          <button type="button" className={btn} disabled={busy || !text.trim()} onClick={() => void decide({ point_id: p.id, state: "edit", text }).then(() => { setMode(null); setAgain(false); })}>Save my wording</button>
        </div>
      )}
      {mode === "remove" && (
        <div className="space-y-1">
          <input aria-label="Why it is removed" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="One line: why this point goes" className="w-full rounded border border-ink-500 bg-ink-900 p-2 text-sm text-slateish-100" />
          <p className="text-xs text-slateish-400">A removed point leaves the CRS sheets; it stays in the record with this reason.</p>
          <button type="button" className={btn} disabled={busy || reason.trim().length < 10} onClick={() => void decide({ point_id: p.id, state: "remove", reason }).then(() => { setMode(null); setAgain(false); })}>Remove it</button>
        </div>
      )}
    </div>
  );
}

function Row({ p, open, onToggle, decide, busy, onViewPage }: {
  p: ReviewPoint; open: boolean; onToggle: () => void; decide: Decide; busy: boolean;
  onViewPage: (d: string, page: number) => void;
}) {
  return (
    <li data-testid="v2-point" className="rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <button type="button" aria-expanded={open} onClick={onToggle} className="flex min-w-[14rem] flex-1 flex-col items-start gap-1 text-left">
          <Pill p={p} />
          <span className="text-slateish-100">{p.name}</span>
          <span className="text-xs text-slateish-400">{placeWords(p)}</span>
        </button>
        <Controls p={p} decide={decide} busy={busy} />
      </div>
      {open && (
        <div className="mt-3 space-y-3" data-testid="v2-open-point">
          {p.action && <p className="text-sm text-slateish-100">{p.action}</p>}
          {tagsWords(p) && (
            <details data-testid="v2-tags" className="text-xs text-slateish-300">
              <summary className="cursor-pointer">{tagsWords(p)}</summary>
              <p className="mt-1 break-words text-slateish-200">{(p.tags ?? []).join(", ")}</p>
            </details>
          )}
          {p.route_note && <p className="text-xs text-slateish-300">{p.route_note}</p>}
          <Boxes p={p} onViewPage={onViewPage} />
          <p className="text-xs text-slateish-400">
            {p.source_words}{p.engine ? ` · ${p.engine}` : ""}{p.decision.state ? ` · ${stateWords(p)}` : " · Not decided"}
          </p>
        </div>
      )}
    </li>
  );
}

type Item = { kind: "one"; p: ReviewPoint } | { kind: "group"; key: string; points: ReviewPoint[] };

function items(points: ReviewPoint[]): Item[] {
  const out: Item[] = []; const seen = new Map<string, Item & { kind: "group" }>();
  for (const p of points) {
    if (p.group_key && p.n_alike > 1) {
      const g = seen.get(p.group_key);
      if (g) g.points.push(p);
      else { const n = { kind: "group" as const, key: p.group_key, points: [p] }; seen.set(p.group_key, n); out.push(n); }
    } else out.push({ kind: "one", p });
  }
  return out;
}

export function PointsList({ points, decide, keepAll, busy, onViewPage }: {
  points: ReviewPoint[]; decide: Decide; keepAll: (ids: string[]) => Promise<boolean>; busy: boolean; onViewPage: (d: string, page: number) => void;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  const list = useMemo(() => items(points), [points]);
  if (!points.length) return <p data-testid="v2-empty" className="text-sm text-slateish-300">No points match this filter.</p>;
  return (
    <ol data-testid="v2-points" className="space-y-2">
      {list.map((it) => {
        if (it.kind === "one") {
          return <Row key={it.p.id} p={it.p} open={openId === it.p.id} onToggle={() => setOpenId(openId === it.p.id ? null : it.p.id)} decide={decide} busy={busy} onViewPage={onViewPage} />;
        }
        const first = it.points[0]; const expanded = openGroups.has(it.key);
        const undecided = it.points.filter((q) => !q.decision.state);
        return (
          <li key={it.key} data-testid="v2-group" className="space-y-2 rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex min-w-[14rem] flex-1 flex-col items-start gap-1">
                <Pill p={{ ...first, pill: `${first.pill.split(" · ")[0]} · ${it.points.length} alike` }} />
                <span className="text-slateish-100">{first.name}</span>
                <span className="text-xs text-slateish-400" data-testid="v2-group-place">{groupPlaceWords(it.points)}</span>
              </div>
              <div className="flex gap-2 text-xs">
                <button type="button" disabled={busy || undecided.length === 0} onClick={() => void keepAll(undecided.map((q) => q.id))}
                  className="rounded-[var(--radius-sm)] border border-ink-500 px-2.5 py-1 text-slateish-100 hover:bg-ink-700 disabled:opacity-50">Keep all</button>
                <button type="button" aria-expanded={expanded} onClick={() => setOpenGroups((s) => { const n = new Set(s); if (n.has(it.key)) n.delete(it.key); else n.add(it.key); return n; })}
                  className="rounded-[var(--radius-sm)] border border-ink-500 px-2.5 py-1 text-slateish-100 hover:bg-ink-700">{expanded ? "Close the group" : `Open the ${it.points.length}`}</button>
              </div>
            </div>
            {expanded && (
              <ol className="space-y-2">
                {it.points.map((q) => <Row key={q.id} p={q} open={openId === q.id} onToggle={() => setOpenId(openId === q.id ? null : q.id)} decide={decide} busy={busy} onViewPage={onViewPage} />)}
              </ol>
            )}
          </li>
        );
      })}
    </ol>
  );
}
