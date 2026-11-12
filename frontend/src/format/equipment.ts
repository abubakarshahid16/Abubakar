/** The equipment cell of a list: the first tag and "and N more" (the full list stays in the tooltip). Nothing for no tags. */
export function equipmentLabel(tags: readonly string[] | null | undefined): string {
  const list = (tags ?? []).map((t) => t.trim()).filter(Boolean);
  if (list.length === 0) return "";
  if (list.length === 1) return list[0];
  const more = list.length - 1;
  return `${list[0]} and ${more} more`;
}
