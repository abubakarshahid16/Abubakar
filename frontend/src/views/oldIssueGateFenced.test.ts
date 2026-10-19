/**
 * Order 121 Part A: from the comment sheet and everything it links to, no
 * path reaches the old issue gate (one line per raw finding, "Item 149 has
 * no engineer's decision", engine notes in the open). The review is signed
 * on the sheet's "Before you sign" box only.
 *
 * The screens under /review/:id are the comment sheet, the card view and its
 * behind-the-scenes pages; this reads every source file of the app and fails
 * if the old panel, or its per-finding sentence, comes back anywhere.
 */
import { describe, expect, it } from "vitest";

const sources = import.meta.glob(["/src/**/*.ts", "/src/**/*.tsx", "!/src/**/*.test.ts", "!/src/**/*.test.tsx"], {
  query: "?raw", import: "default", eager: true,
}) as Record<string, string>;

describe("the old issue gate is fenced off (order 121)", () => {
  it("reads the app's sources (not vacuous)", () => {
    const names = Object.keys(sources);
    expect(names.some((n) => n.endsWith("views/CrsSheetView.tsx"))).toBe(true);
    expect(names.some((n) => n.endsWith("panels/BehindTheScenes.tsx"))).toBe(true);
    expect(names.length).toBeGreaterThan(50);
  });

  it("no screen renders the old gate panel or its per-finding line", () => {
    const offenders = Object.entries(sources)
      .filter(([, text]) => /CrsIssueGatePanel|has no engineer's decision|Not ready to issue to the contractor/.test(text))
      .map(([name]) => name);
    expect(offenders).toEqual([]);
  });

  it("only the comment sheet issues the contractor's copy", () => {
    const issuers = Object.entries(sources)
      .filter(([, text]) => /downloadCrs\(\w+, "issue"\)|exportSheet\("issue"\)/.test(text))
      .map(([name]) => name.replace(/^\//, ""));
    expect(issuers).toEqual(["src/views/CrsSheetView.tsx"]);
  });
});
