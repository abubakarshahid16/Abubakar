/** SPEC 7: "How it was reviewed": everything of today's Details under one tab: how this was reviewed, the rules used, the standards
 *  and the book table, the steps, the numbers and the findings. Each part is drawn when opened (nothing is read until then). */
import { type ReactNode, useEffect, useState } from "react";

import { type MethodInfo, fetchMethod, localOnlyWords, methodLine } from "./words";

export interface HowSection { id: string; title: string; render: () => ReactNode }

/** The method and its fixed words, read from the route (never written here). Null while loading or when the route is unreachable. */
export function useMethodInfo(): MethodInfo | null {
  const [info, setInfo] = useState<MethodInfo | null>(null);
  useEffect(() => {
    let live = true;
    void fetchMethod().then((r) => { if (live && r.ok) setInfo(r.data); });
    return () => { live = false; };
  }, []);
  return info;
}

export function HowTab({ top, sections }: { top: ReactNode; sections: HowSection[] }) {
  const [opened, setOpened] = useState<Set<string>>(new Set());
  const info = useMethodInfo();
  const line = methodLine(info);
  const local = localOnlyWords(info);
  return (
    <div className="space-y-3" data-testid="v2-how">
      {line && <p className="text-sm text-slateish-100" data-testid="v2-how-method">{line}</p>}
      {local && <p className="text-xs text-slateish-300" data-testid="v2-how-local">{local}</p>}
      {top}
      {sections.map((s) => (
        <details key={s.id} data-testid={`v2-how-${s.id}`} className="rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-3"
          onToggle={(e) => { if ((e.currentTarget as HTMLDetailsElement).open) setOpened((o) => new Set(o).add(s.id)); }}>
          <summary className="cursor-pointer text-sm font-semibold text-slateish-100">{s.title}</summary>
          <div className="mt-3">{opened.has(s.id) ? s.render() : null}</div>
        </details>
      ))}
    </div>
  );
}
