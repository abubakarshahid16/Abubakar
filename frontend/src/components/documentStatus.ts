/**
 * How a document's state is presented.
 *
 * Kept apart from the components so the rules can be tested directly, because
 * these are the rules that have been got wrong repeatedly on the backend:
 *
 *  - a document is never called "ready" until embedding has finished
 *  - `no_searchable_content` is a WARNING, never a success, and always carries
 *    its reason
 *  - a low retrievable ratio is surfaced loudly, because the quality gate
 *    over-rejecting an unfamiliar layout is otherwise silent
 */
import type { DocumentRecord } from "../types/api";

export type Tone = "neutral" | "progress" | "success" | "warning" | "danger";

export interface StatusPresentation {
  label: string;
  tone: Tone;
  /** true when the document can already answer questions */
  answerable: boolean;
}

export function presentStatus(doc: DocumentRecord): StatusPresentation {
  switch (doc.status) {
    case "queued":
      return { label: "queued", tone: "neutral", answerable: false };
    case "extracting":
      return { label: "extracting pages", tone: "progress", answerable: false };
    case "chunking":
      return { label: "chunking", tone: "progress", answerable: false };
    case "indexing_keyword":
      return { label: "building keyword index", tone: "progress", answerable: false };
    case "partially_searchable":
      return { label: "partially searchable", tone: "progress", answerable: true };
    case "ready":
      // ONE status, and never "ready" beside "2 awaiting OCR". The README makes
      // this an invariant: a partially-processed document must never read as
      // ready. The backend can reach status='ready' with scanned pages still
      // unread - recognition runs after the keyword index - so the screen
      // resolves the contradiction rather than displaying both halves of it.
      if (doc.needs_ocr_pages > doc.recognised_pages) {
        return {
          label: "reading scanned pages",
          tone: "progress",
          answerable: true,
        };
      }
      return { label: "ready", tone: "success", answerable: true };
    case "no_searchable_content":
      // Finished, but nothing can be searched. Calling this a success would
      // tell an operator the document is usable when it answers nothing.
      return { label: "no searchable content", tone: "warning", answerable: false };
    case "failed":
      return { label: "failed", tone: "danger", answerable: false };
    default:
      return { label: String(doc.status), tone: "neutral", answerable: false };
  }
}

const nf = new Intl.NumberFormat("en-GB");

/**
 * The progress line, e.g.
 *   "1,204 pages · 2,831 passages · keyword search ready · 340/2831 embedded"
 */
export function progressLine(doc: DocumentRecord): string {
  const parts: string[] = [];
  if (doc.page_count != null) {
    parts.push(`${nf.format(doc.page_count)} pages`);
  } else if (doc.pages_done > 0) {
    parts.push(`${nf.format(doc.pages_done)} pages so far`);
  }

  if (doc.chunk_count_total > 0) {
    // "passages", the word the Dashboard defines. This line said
    // "sections" while the same object was "chunks" on a button and
    // "passages" on the Dashboard - three names, one thing.
    parts.push(`${nf.format(doc.chunk_count)} passages`);
  }

  if (doc.status === "no_searchable_content") {
    parts.push("nothing searchable");
    return parts.join(" · ");
  }

  if (doc.status === "partially_searchable" || doc.status === "ready") {
    parts.push("keyword search ready");
  }

  if (doc.chunk_count > 0) {
    parts.push(
      doc.embedded_count >= doc.chunk_count
        ? `${nf.format(doc.chunk_count)} embedded`
        : `${nf.format(doc.embedded_count)}/${nf.format(doc.chunk_count)} embedded`,
    );
  }
  return parts.join(" · ");
}

export function embedProgress(doc: DocumentRecord): number {
  if (doc.chunk_count <= 0) return 0;
  return Math.min(1, doc.embedded_count / doc.chunk_count);
}

/** Excluded chunk rows - what search cannot see. */
export function excludedCount(doc: DocumentRecord): number {
  return Math.max(0, doc.chunk_count_total - doc.chunk_count);
}

export function retrievableRatio(doc: DocumentRecord): number | null {
  if (doc.chunk_count_total <= 0) return null;
  return doc.chunk_count / doc.chunk_count_total;
}

/** Below this, the gate is probably mishandling an unfamiliar layout. */
export const LOW_RETRIEVABLE_THRESHOLD = 0.6;

export function hasLowRetrievableRatio(doc: DocumentRecord): boolean {
  const ratio = retrievableRatio(doc);
  return ratio !== null && ratio < LOW_RETRIEVABLE_THRESHOLD;
}

export function formatAge(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}
