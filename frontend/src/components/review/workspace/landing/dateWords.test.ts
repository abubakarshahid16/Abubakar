import { describe, expect, it } from "vitest";
import { dayTimeWords, dayWords } from "./dateWords";

describe("dateWords (one date style)", () => {
  const at = new Date(2026, 9, 19, 12, 20).toISOString();
  it("says day month year", () => {
    expect(dayWords(at)).toBe("19 Oct 2026");
    expect(dayWords(new Date(2026, 0, 3, 9, 5).toISOString())).toBe("3 Jan 2026");
  });
  it("adds the time as hours and minutes", () => {
    expect(dayTimeWords(at)).toBe("19 Oct 2026, 12:20");
    expect(dayTimeWords(new Date(2026, 0, 3, 9, 5).toISOString())).toBe("3 Jan 2026, 09:05");
  });
  it("says nothing when the date is not known or not readable", () => {
    for (const v of [null, undefined, "", "not a date"]) {
      expect(dayWords(v)).toBe("");
      expect(dayTimeWords(v)).toBe("");
    }
  });
});
