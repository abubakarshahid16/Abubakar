/** OWNER: builder C. A code in plain words, raw code under "Details" (PLACEHOLDER). */
import type { PlainTermProps } from "./contract";
import { plainWords } from "./plainWords";

export function PlainTerm({ code, kind = "any" }: PlainTermProps) {
  const entry = plainWords(code, kind);
  if (!entry.words) return null;
  return <span>{entry.words}</span>;
}
