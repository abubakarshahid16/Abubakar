/**
 * The building blocks of "How this was reviewed": a titled section with its
 * one-sentence explanation, a fact row (label, value, the stored field it
 * came from) and a reason table. A fact whose value is null prints
 * NOT_RECORDED - the honesty rule lives here once, not in seven sections.
 */
import type { ReactNode } from "react";

import { NOT_RECORDED, type Sourced } from "./howData";

export interface HowSectionMeta {
  id: string;
  number: number;
  title: string;
  /** The one sentence a non-technical manager reads first. */
  explains: string;
}

export function HowSection({ meta, children }: { meta: HowSectionMeta; children: ReactNode }) {
  return (
    <section id={meta.id} aria-labelledby={`${meta.id}-title`} data-testid={`how-${meta.id}`}
      className="scroll-mt-20 space-y-3 break-inside-avoid rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-4 print:border-0 print:p-0">
      <header>
        <h2 id={`${meta.id}-title`} className="text-lg font-semibold text-slateish-100">
          {meta.number}. {meta.title}
        </h2>
        <p className="mt-0.5 text-sm text-slateish-300">{meta.explains}</p>
      </header>
      {children}
    </section>
  );
}

/** The value as text: a number, a list of pages, a string, or NOT_RECORDED. */
export function factText(value: unknown): string {
  if (value === null || value === undefined) return NOT_RECORDED;
  if (typeof value === "number") return value.toLocaleString();
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.length === 0 ? "none" : value.map(String).join(", ");
  return String(value);
}

export function Fact({ label, fact, detail, testId }: {
  label: string;
  fact: Sourced<unknown>;
  /** Extra words after the value (a page list, a model name). */
  detail?: ReactNode;
  testId?: string;
}) {
  const recorded = fact.value !== null && fact.value !== undefined;
  return (
    <div data-testid={testId} className="grid gap-x-4 gap-y-0.5 py-1.5 sm:grid-cols-[14rem_minmax(0,1fr)]">
      <dt className="text-sm text-slateish-300">{label}</dt>
      <dd className="min-w-0">
        <span className={recorded ? "text-sm font-medium text-slateish-100" : "text-sm italic text-slateish-400"}>
          {factText(fact.value)}
        </span>
        {recorded && detail ? <span className="ml-1 text-sm text-slateish-300">{detail}</span> : null}
        <span className="block text-xs text-slateish-500">from {fact.source}</span>
      </dd>
    </div>
  );
}

export function FactList({ children, label }: { children: ReactNode; label: string }) {
  return <dl aria-label={label} className="divide-y divide-ink-700">{children}</dl>;
}

/** A small two-column table: a reason and how many, as the run stored them. */
export function ReasonTable({ caption, rows, source, testId }: {
  caption: string;
  rows: { reason: string; count: number }[];
  source: string;
  testId?: string;
}) {
  if (rows.length === 0) return <p className="text-sm italic text-slateish-400">{caption}: {NOT_RECORDED}</p>;
  return (
    <table data-testid={testId} className="w-full text-sm">
      <caption className="pb-1 text-left text-sm text-slateish-300">
        {caption} <span className="text-xs text-slateish-500">(from {source})</span>
      </caption>
      <thead>
        <tr className="text-left text-xs text-slateish-400">
          <th scope="col" className="py-1 pr-3 font-medium">Reason</th>
          <th scope="col" className="py-1 text-right font-medium">Clauses</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.reason} className="border-t border-ink-700">
            <td className="py-1 pr-3 text-slateish-200">{row.reason}</td>
            <td className="py-1 text-right tabular-nums text-slateish-100">{row.count.toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
