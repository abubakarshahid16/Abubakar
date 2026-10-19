/**
 * OWNER: builder B. D1: where the panel goes after a decision: the next
 * comment still to decide after `fromKey`, in sheet order, wrapping round to
 * the first; never `fromKey` itself. null when nothing is left.
 * `undecidedKeys` is `ReviewNumbers.undecidedKeys` (the one source).
 */
export function nextUndecided(orderKeys: string[], undecidedKeys: string[], fromKey: string): string | null {
  const left = new Set(undecidedKeys.filter((key) => key !== fromKey));
  if (left.size === 0) return null;
  const at = orderKeys.indexOf(fromKey);
  for (let i = 1; i <= orderKeys.length; i += 1) {
    const key = orderKeys[(at + i + orderKeys.length) % orderKeys.length];
    if (left.has(key)) return key;
  }
  // A key not on the sheet any more: the first one left.
  return undecidedKeys.find((key) => left.has(key)) ?? null;
}
