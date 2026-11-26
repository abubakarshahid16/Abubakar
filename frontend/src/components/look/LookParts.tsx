/**
 * THE NEW LOOK'S SMALL PARTS (owner, 26 Nov 2026, on the Dashboard screenshot): used only while the way-back switch is on (`NEW_LOOK`),
 * so the classic look keeps its own markup exactly. The same words and numbers: a long sentence is FOLDED behind "Details" (or an
 * info button), never cut or dropped; a status keeps its word and gains the spec's colour (never colour alone).
 */
import type { ReactNode } from "react";
import "../kit/kit.css";

import type { ChipTone } from "./lookTone";

/** A tile's line: shown whole when it is short; a long one folds behind "Details" (owner: "at most one short line under it"). */
export const SHORT_LINE = 60;

export function TileLine({ text, className = "", inverted = false }: { text: ReactNode; className?: string; inverted?: boolean }) {
  const colour = inverted ? "" : "text-slateish-300";
  if (typeof text !== "string" || text.length <= SHORT_LINE) {
    return <p className={`mt-2 text-sm leading-snug ${colour} ${className}`}>{text}</p>;
  }
  return (
    <details className={`look-details mt-2 text-sm ${colour} ${className}`}>
      <summary className={`cursor-pointer select-none text-xs font-semibold hover:underline ${inverted ? "" : "text-signal-300"}`}>Details</summary>
      <p className="mt-1 leading-snug">{text}</p>
    </details>
  );
}

/** A paragraph of background moved out of the way (owner: "move it to the bottom or behind an info icon"): an info button that opens it. */
export function InfoFold({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  return (
    <details className={`look-details text-sm text-slateish-300 ${className}`}>
      <summary className="inline-flex cursor-pointer select-none items-center gap-1.5 text-xs font-semibold text-slateish-400 hover:text-slateish-200">
        <InfoIcon />
        {title}
      </summary>
      <div className="mt-2 max-w-3xl leading-relaxed">{children}</div>
    </details>
  );
}


/** A long section folded under the new look (owner: the main thing first, detail folded): its heading stays visible as the fold's
 *  summary, with its count, so nothing waiting is hidden from view; the classic look shows the heading and body as before. */
export function SectionFold({ on, heading, children }: { on: boolean; heading: ReactNode; children: ReactNode }) {
  if (!on) return <>{heading}{children}</>;
  return (
    <details className="look-details flex flex-col gap-2">
      <summary className="cursor-pointer select-none">
        {heading}
        <span className="ml-2 text-xs font-semibold text-signal-300 hover:underline">Show</span>
      </summary>
      <div className="mt-2 flex flex-col gap-2">{children}</div>
    </details>
  );
}

/** The old chip classes (kept for the record; the kit's chip draws them now). */
export const CHIP: Record<ChipTone, string> = {
  done: "border-pill-pass-border bg-pill-pass-bg text-pill-pass-fg",
  check: "border-pill-review-border bg-pill-review-bg text-pill-review-fg",
  late: "border-pill-fail-border bg-pill-fail-bg text-pill-fail-fg",
  info: "border-pill-cond-border bg-pill-cond-bg text-pill-cond-fg",
  plain: "border-ink-600 bg-ink-800 text-slateish-300",
};

/** A status as a chip: its word, in the spec's colour (Signed off green, Not signed off amber, Late red). */
export function StatusChip({ tone, children }: { tone: ChipTone; children: ReactNode }) {
  // THE SHARED KIT'S CHIP (owner, 27 Nov 2026 03:30: chips boxed here and plain there): the same shape and tone colours as the kit's
  // StatusChip on every page; these tones map one to one (done, check, late, info, plain)
  return <span className={`kit-chip kit-chip--${tone}`}>{children}</span>;
}

function Svg({ children }: { children: ReactNode }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
      {children}
    </svg>
  );
}

export function InfoIcon() {
  return <Svg><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></Svg>;
}

/** One plain line icon per menu item (no emoji, no outside icon set: drawn here). */
export function NavIcon({ id }: { id: string }) {
  switch (id) {
    case "dashboard":
      return <Svg><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></Svg>;
    case "review":
      return <Svg><path d="M9 11l2 2 4-4" /><path d="M5 3h10l4 4v14H5z" /></Svg>;
    case "documents":
      return <Svg><path d="M7 3h7l5 5v13H7z" /><path d="M14 3v5h5" /></Svg>;
    case "standards":
      return <Svg><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z" /><path d="M4 19a2 2 0 0 1 2-2h13" /></Svg>;
    case "analysis":
      return <Svg><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></Svg>;
    case "chat":
      return <Svg><path d="M4 5h16v11H8l-4 4z" /></Svg>;
    case "reports":
      return <Svg><path d="M6 3h12v18H6z" /><path d="M9 8h6M9 12h6M9 16h4" /></Svg>;
    case "deliverables":
      return <Svg><path d="M3 7l9-4 9 4-9 4z" /><path d="M3 7v10l9 4 9-4V7" /></Svg>;
    case "ingestion":
      return <Svg><path d="M12 3v12M7 10l5 5 5-5" /><path d="M4 19h16" /></Svg>;
    case "technicalQueries":
      return <Svg><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7M12 17h.01" /></Svg>;
    case "admin":
      return <Svg><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></Svg>;
    default:
      return <Svg><circle cx="12" cy="12" r="3" /></Svg>;
  }
}
