/**
 * Pure helpers for the Standards Library list: the name a person reads, the family a book belongs to, the search, the groups.
 * Nothing here is invented: a name comes from the stored number or title, then the file name; a family is read from the
 * words of those same strings and is "Other" when none matches. Counts are always counts of the rows given.
 */
import type { StandardSummary } from "../types/api";

export const FAMILIES = ["SAES", "API", "ASME", "ISO", "NACE", "Other"] as const;
export type Family = (typeof FAMILIES)[number];

const FAMILY_WORDS: ReadonlyArray<readonly [Family, RegExp]> = [
  ["SAES", /(^|[^a-z])saes([^a-z]|$)/i],
  ["API", /(^|[^a-z])api([^a-z]|$)/i],
  ["ASME", /(^|[^a-z])asme([^a-z]|$)/i],
  ["ISO", /(^|[^a-z])iso([^a-z]|$)/i],
  ["NACE", /(^|[^a-z])nace([^a-z]|$)/i],
];

/** The family of a standard: read from its number, then its file name, then its title. "Other" when none says. */
export function familyOf(s: Pick<StandardSummary, "document_number" | "filename" | "title">): Family {
  for (const text of [s.document_number, s.filename, s.title]) {
    if (!text) continue;
    for (const [family, pattern] of FAMILY_WORDS) if (pattern.test(text)) return family;
  }
  return "Other";
}

/** What the row is called: the stored number, else the stored title, else the file name. Never made up. */
export function displayName(s: Pick<StandardSummary, "document_number" | "filename" | "title">): string {
  return s.document_number?.trim() || s.title?.trim() || s.filename;
}

/** Rows matching every word of the search, in the name, number, title, file name, family or discipline. */
export function searchStandards(rows: readonly StandardSummary[], query: string): StandardSummary[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [...rows];
  return rows.filter((s) => {
    const hay = [
      s.document_number, s.title, s.filename, familyOf(s), s.discipline_canonical, s.discipline, s.revision,
    ].filter(Boolean).join(" ").toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

export interface FamilyGroup { family: Family; rows: StandardSummary[] }

/** Groups in the fixed order of FAMILIES; empty groups are left out; rows sorted by name inside a group. */
export function groupByFamily(rows: readonly StandardSummary[]): FamilyGroup[] {
  const by = new Map<Family, StandardSummary[]>();
  for (const row of rows) {
    const family = familyOf(row);
    by.set(family, [...(by.get(family) ?? []), row]);
  }
  return FAMILIES.filter((f) => by.has(f)).map((family) => ({
    family,
    rows: [...(by.get(family) ?? [])].sort((a, b) =>
      displayName(a).localeCompare(displayName(b), undefined, { numeric: true, sensitivity: "base" })),
  }));
}
