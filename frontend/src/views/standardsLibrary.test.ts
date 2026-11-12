import { describe, expect, it } from "vitest";

import { displayName, familyOf, groupByFamily, searchStandards } from "./standardsLibrary";
import type { StandardSummary } from "../types/api";

const row = (over: Partial<StandardSummary>): StandardSummary => ({
  id: "d", filename: "x.pdf", status: "ready", page_count: 1, uploaded_at: "2026-01-01T00:00:00Z",
  title: null, document_number: null, revision: null, effective_date: null, discipline: null,
  superseded_by: null, superseded: false, requirement_count: 0, awaiting_verification: 0, ...over,
});

describe("displayName", () => {
  it("uses the stored number, then the stored title, then the file name; never makes one up", () => {
    expect(displayName(row({ document_number: "API 610", title: "Pumps", filename: "a.pdf" }))).toBe("API 610");
    expect(displayName(row({ title: "Pumps", filename: "a.pdf" }))).toBe("Pumps");
    expect(displayName(row({ filename: "1234.pdf" }))).toBe("1234.pdf");
  });
});

describe("familyOf", () => {
  it("reads the family from the number, then the file name, then the title", () => {
    expect(familyOf(row({ document_number: "SAES-A-105" }))).toBe("SAES");
    expect(familyOf(row({ filename: "API_610_2021.pdf" }))).toBe("API");
    expect(familyOf(row({ filename: "x.pdf", title: "ASME B31.3 piping" }))).toBe("ASME");
    // the number outranks the title and the file name; the earliest word in one text wins
    expect(familyOf(row({ document_number: "ISO 9001", title: "Quality, see API 610", filename: "api.pdf" }))).toBe("ISO");
    expect(familyOf(row({ title: "ISO 9001 (see API 610)" }))).toBe("ISO");
    expect(familyOf(row({ filename: "ISO-9001.pdf" }))).toBe("ISO");
    expect(familyOf(row({ filename: "NACE MR0175.pdf" }))).toBe("NACE");
  });
  it("is Other when nothing says, and does not match a word that only contains a family name", () => {
    expect(familyOf(row({ filename: "123.pdf" }))).toBe("Other");
    expect(familyOf(row({ filename: "rapid_steel.pdf" }))).toBe("Other");
  });
});

describe("searchStandards", () => {
  const rows = [
    row({ id: "1", document_number: "SAES-A-105", title: "Coating systems" }),
    row({ id: "2", filename: "API 610.pdf", discipline: "Mechanical" }),
    row({ id: "3", filename: "55.pdf" }),
  ];
  it("keeps everything for an empty search", () => {
    expect(searchStandards(rows, "  ")).toHaveLength(3);
  });
  it("needs every word, in the name, title, family or discipline", () => {
    expect(searchStandards(rows, "coating saes").map((r) => r.id)).toEqual(["1"]);
    expect(searchStandards(rows, "mechanical").map((r) => r.id)).toEqual(["2"]);
    expect(searchStandards(rows, "api").map((r) => r.id)).toEqual(["2"]);
    expect(searchStandards(rows, "nothing here")).toEqual([]);
  });
});

describe("groupByFamily", () => {
  it("groups in a fixed order, drops empty groups, keeps every row once, sorts by name", () => {
    const rows = [
      row({ id: "a", filename: "55.pdf" }),
      row({ id: "b", document_number: "SAES-B-2" }),
      row({ id: "c", document_number: "SAES-B-10" }),
      row({ id: "d", filename: "API 5L.pdf" }),
    ];
    const groups = groupByFamily(rows);
    expect(groups.map((g) => g.family)).toEqual(["SAES", "API", "Other"]);
    expect(groups[0].rows.map((r) => r.id)).toEqual(["b", "c"]);
    expect(groups.reduce((n, g) => n + g.rows.length, 0)).toBe(rows.length);
  });
});
