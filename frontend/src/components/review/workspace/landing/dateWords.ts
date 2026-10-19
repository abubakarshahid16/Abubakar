/**
 * v2.2: one date style on the first page, the all-reviews list, the past
 * reviews list and the Compare window: day month year, e.g. "19 Oct 2026",
 * and "19 Oct 2026, 12:20" where a time is shown. Built by hand (not the
 * browser's locale) so every screen and every machine says it the same way.
 * Unknown or unreadable values give "" (nothing), never a made-up date.
 */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parsed(value: string | null | undefined): Date | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/** "19 Oct 2026"; "" when not known. */
export function dayWords(value: string | null | undefined): string {
  const d = parsed(value);
  return d ? `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}` : "";
}

/** "19 Oct 2026, 12:20" (24-hour, local time); "" when not known. */
export function dayTimeWords(value: string | null | undefined): string {
  const d = parsed(value);
  return d ? `${dayWords(value)}, ${pad(d.getHours())}:${pad(d.getMinutes())}` : "";
}
