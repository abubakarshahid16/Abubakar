/** The admin grant list: search by file name, then one page at a time. Narrowing only: it hides rows, it changes no grant. */
import type { AdminGrantDocument } from "../types/admin";

export const GRANT_PAGE_SIZE = 25;

export function filterGrantDocuments(
  documents: readonly AdminGrantDocument[], query: string,
): AdminGrantDocument[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [...documents];
  return documents.filter((d) => {
    const hay = d.filename.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/** The page asked for, kept inside the real page range (a search can leave fewer pages than the reader was on). */
export function grantPage<T>(rows: readonly T[], page: number, size = GRANT_PAGE_SIZE) {
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const index = Math.min(Math.max(0, page), pages - 1);
  return { rows: rows.slice(index * size, (index + 1) * size), index, pages };
}
