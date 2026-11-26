/**
 * THE SMALL COMPONENT SET of the one design system (owner, 26 Nov 2026, G9). Every part draws only from the tokens (look.css and
 * index.css), so it reads right in the classic and the new look, light and dark. Plain words; no internal terms.
 *
 * The status chip keeps the app's honest labels exactly: "AI, to be checked" until an engineer signs, "Rough draft", "Signed",
 * "Waiting", "Failed".
 */
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Tone = "primary" | "secondary" | "quiet" | "danger";

const BUTTON: Record<Tone, string> = {
  primary: "bg-signal-500 text-white hover:bg-signal-400 shadow-[var(--shadow-resting)]",
  secondary: "border border-ink-500 bg-ink-800 text-slateish-100 hover:bg-ink-700",
  quiet: "text-slateish-200 hover:bg-ink-700",
  danger: "border border-danger-500 bg-ink-800 text-danger-500 hover:bg-ink-700",
};

export function Button({ tone = "secondary", size = "md", className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: Tone;
  size?: "md" | "lg";
}) {
  const sizing = size === "lg" ? "px-5 py-3 text-base" : "px-4 py-2 text-sm";
  return (
    <button
      type="button"
      {...rest}
      className={`inline-flex items-center justify-center gap-2 rounded-[var(--radius-sm)] font-semibold motion-safe:transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${sizing} ${BUTTON[tone]} ${className}`}
    />
  );
}

export function Card({ children, className = "", as: Tag = "div", ...rest }: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "li" | "article";
  [key: `data-${string}`]: string | undefined;
}) {
  return (
    <Tag {...rest} className={`rounded-[var(--radius-md)] border border-ink-600 bg-ink-800 p-5 shadow-[var(--shadow-resting)] ${className}`}>
      {children}
    </Tag>
  );
}

export type Status = "ai" | "draft" | "signed" | "waiting" | "failed";

/** The honest labels, word for word. */
export const STATUS_WORDS: Record<Status, string> = {
  ai: "AI, to be checked",
  draft: "Rough draft",
  signed: "Signed",
  waiting: "Waiting",
  failed: "Failed",
};

const STATUS_STYLE: Record<Status, string> = {
  ai: "border-pill-review-border bg-pill-review-bg text-pill-review-fg",
  draft: "border-ink-500 bg-ink-700 text-slateish-200",
  signed: "border-pill-pass-border bg-pill-pass-bg text-pill-pass-fg",
  waiting: "border-pill-cond-border bg-pill-cond-bg text-pill-cond-fg",
  failed: "border-pill-fail-border bg-pill-fail-bg text-pill-fail-fg",
};

export function StatusChip({ status, children }: { status: Status; children?: ReactNode }) {
  return (
    <span data-status={status}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-[var(--radius-full)] border px-2.5 py-0.5 text-xs font-semibold ${STATUS_STYLE[status]}`}>
      {children ?? STATUS_WORDS[status]}
    </span>
  );
}

/** A page's top: its title, ONE line on what it is for and what to do next, and its main actions. */
export function PageHeader({ title, purpose, actions, id }: { title: string; purpose: string; actions?: ReactNode; id?: string }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 id={id} className="text-[length:var(--t-xl)] font-bold leading-tight text-slateish-100">{title}</h1>
        <p className="mt-1 max-w-3xl text-[length:var(--t-sm)] text-slateish-300" data-testid="page-purpose">{purpose}</p>
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="font-semibold text-slateish-200">{label}</span>
      <span className="mt-1 block">{children}</span>
      {hint && <span className="mt-1 block text-xs text-slateish-400">{hint}</span>}
    </label>
  );
}

export const INPUT =
  "w-full rounded-[var(--radius-sm)] border border-ink-500 bg-ink-800 px-3 py-2 text-sm text-slateish-100 placeholder:text-slateish-500";

/** A table that never scrolls the page sideways: on a narrow window it scrolls inside its own box. */
export function DataTable({ head, rows, caption }: { head: string[]; rows: ReactNode[][]; caption: string }) {
  return (
    <div className="overflow-x-auto rounded-[var(--radius-md)] border border-ink-600">
      <table className="w-full min-w-[36rem] text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-ink-700 text-xs uppercase tracking-wide text-slateish-400">
          <tr>{head.map((h) => <th key={h} scope="col" className="px-4 py-2 font-semibold">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((cells, r) => (
            <tr key={r} className="border-t border-ink-600 align-top">
              {cells.map((cell, c) => <td key={c} className="px-4 py-3 text-slateish-200">{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The empty-state pattern: WHY it is empty, and WHAT to press. */
export function Empty({ why, next }: { why: string; next?: ReactNode }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-dashed border-ink-500 bg-ink-850 p-8 text-center">
      <p className="text-slateish-200">{why}</p>
      {next && <div className="mt-4 flex justify-center">{next}</div>}
    </div>
  );
}

/** A folded section: the detail is one click away, never in the way of the answer. */
export function Fold({ title, children, open = false }: { title: string; children: ReactNode; open?: boolean }) {
  return (
    <details open={open} className="rounded-[var(--radius-md)] border border-ink-600 bg-ink-800">
      <summary className="cursor-pointer px-5 py-3 text-sm font-semibold text-slateish-200">{title}</summary>
      <div className="border-t border-ink-600 px-5 py-4 text-sm text-slateish-300">{children}</div>
    </details>
  );
}
