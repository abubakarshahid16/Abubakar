import { describe, expect, it } from "vitest";

import { formatWhen, formatWhenDate, zoneLabel } from "./when";

/** What the reader's own clock says for an instant: the expected text is built from the same Date, so the test holds in any zone. */
function local(utc: string): string {
  const d = new Date(utc);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}, ${p(d.getHours())}:${p(d.getMinutes())} ${zoneLabel(d)}`.trimEnd();
}

describe("formatWhen: one date format", () => {
  it("reads every server shape as the same UTC instant", () => {
    const want = local("2026-09-30T18:48:03Z");
    expect(formatWhen("2026-09-30T18:48:03Z")).toBe(want);
    expect(formatWhen("2026-09-30 18:48:03+00:00")).toBe(want);
    expect(formatWhen("2026-09-30T18:48:03.123456+00:00")).toBe(want);
    expect(formatWhen("2026-09-30T18:48:03")).toBe(want); // no zone = UTC, not local
  });
  it("has no seconds, no raw 'T' or 'UTC' and uses the day-month-year order", () => {
    const text = formatWhen("2026-11-12T09:35:59Z");
    expect(text).toMatch(/^\d{1,2} Nov 2026, \d{2}:\d{2}( \S+)?$/);
  });
  it("shows a bare calendar day as that day, with no clock time", () => {
    expect(formatWhen("2026-10-18")).toBe("18 Oct 2026");
  });
  it("shows what it cannot read as it came, and nothing for nothing", () => {
    expect(formatWhen("soon")).toBe("soon");
    expect(formatWhen(null)).toBe("");
    expect(formatWhen(undefined)).toBe("");
    expect(formatWhen("")).toBe("");
  });
  it("formats a Date the same way", () => {
    expect(formatWhenDate(new Date("2026-09-30T18:48:03Z"))).toBe(local("2026-09-30T18:48:03Z"));
  });
  it("names the zone of the reader's clock: a clock time never stands alone", () => {
    const text = formatWhen("2026-11-25T20:20:00Z");
    const zone = zoneLabel(new Date("2026-11-25T20:20:00Z"));
    expect(zone).not.toBe("");
    expect(text.endsWith(` ${zone}`)).toBe(true);
    expect(formatWhen("2026-11-25")).toBe("25 Nov 2026"); // a bare day has no clock time and no zone
  });
});
