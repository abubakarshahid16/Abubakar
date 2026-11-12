/**
 * ONE date format for everything the reader sees: "12 Nov 2026, 14:35", in the reader's own time zone.
 *
 * The server writes times in several shapes ("2026-09-30T18:48:03Z", "2026-09-30 18:48:03+00:00", "2026-09-30T18:48:03"
 * with no zone). All of them are UTC. A value with no zone is read as UTC, never as local time. A value that is not a
 * date is shown as it came (never invented, never "Invalid Date"); nothing gives "".
 */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const HAS_ZONE = /(Z|[+-]\d{2}(:?\d{2})?)$/i;
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

function parse(value: string): Date | null {
  const text = value.trim();
  if (!/^\d{4}-\d{2}-\d{2}/.test(text)) return null;
  if (DATE_ONLY.test(text)) {
    // A calendar day has no clock time: read it as that day, wherever the reader is.
    const [y, m, d] = text.split("-").map(Number);
    return new Date(y, m - 1, d);
  }
  const iso = text.replace(" ", "T");
  const date = new Date(HAS_ZONE.test(iso.slice(10)) ? iso : `${iso}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** "12 Nov 2026, 14:35" (or "12 Nov 2026" for a bare calendar day). */
export function formatWhen(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  const date = parse(value);
  if (!date) return value;
  const day = `${date.getDate()} ${MONTHS[date.getMonth()]} ${date.getFullYear()}`;
  if (DATE_ONLY.test(value.trim())) return day;
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${day}, ${hh}:${mm}`;
}

/** The same for a Date or epoch milliseconds (the page's own "refreshed" stamp). */
export function formatWhenDate(value: Date | number): string {
  return formatWhen(new Date(value).toISOString());
}
