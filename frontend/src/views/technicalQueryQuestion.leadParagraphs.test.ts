/** H's audit #51 (27 Nov 2026): a question section with no list read as one dense wall. Invented text. */
import { describe, expect, it } from "vitest";

import { LEAD_PARA, leadParagraphs } from "./technicalQueryQuestion";

const sentence = (n: number) => `Sentence number ${n} asks about the invented header and its tie-in point, with enough words to be long here.`;

describe("leadParagraphs", () => {
  it("keeps a short paragraph whole", () => {
    expect(leadParagraphs("One short request. Two.")).toEqual(["One short request. Two."]);
  });

  it("breaks a long paragraph into short paragraphs of whole sentences, every word kept in order", () => {
    const text = [1, 2, 3, 4, 5, 6].map(sentence).join(" ");
    const parts = leadParagraphs(text);
    expect(parts.length).toBeGreaterThan(1);
    expect(parts.join(" ")).toBe(text);
    for (const p of parts) expect(p.length).toBeLessThanOrEqual(LEAD_PARA);
    for (const p of parts) expect(p).toMatch(/\.$/);
  });

  it("never breaks after an abbreviation, an initial or a number", () => {
    const filler = "x".repeat(LEAD_PARA);
    const text = `${filler} See No. 5 and Rev. B of the sheet, e.g. Table 2, per J. Doe and item 3. Then the last sentence.`;
    const parts = leadParagraphs(text);
    expect(parts.join(" ")).toBe(text);
    expect(parts.some((p) => /^(5|B|Table|Doe|Then)/.test(p))).toBe(false);
  });

  it("ends a sentence after a standard's number, and gives each inline bullet its own line", () => {
    const filler = "y".repeat(LEAD_PARA);
    const text = `${filler} as in ABC-X-040. Next sentence follows, criteria as follows: \u2022 1.5 litres per day for one use \u2022 19 litres for another use. The last one.`;
    const parts = leadParagraphs(text);
    expect(parts.join(" ")).toBe(text);
    expect(parts).toContain("\u2022 1.5 litres per day for one use");
    expect(parts.some((p) => p.startsWith("Next sentence"))).toBe(true);
    expect(parts.some((p) => p.startsWith("\u2022 19 litres"))).toBe(true);
  });
});
