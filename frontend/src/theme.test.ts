/**
 * Every theme colour a component names must actually exist.
 *
 * Tailwind v4 resolves colours from the `@theme` block. A class naming a
 * colour that was never defined does not error, does not warn, and does not
 * appear in the stylesheet - it simply has no effect. `bg-ink-950` shipped in
 * the page image viewer doing nothing at all, and nothing caught it, because
 * the failure mode of this mistake is silence.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { colourClasses, definedColours } from "./test/themeColours";

const SRC = join(__dirname);
const CSS = join(__dirname, "index.css");

const PALETTES = ["ink", "slateish", "signal", "warn", "danger", "info"];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return sourceFiles(full);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [full] : [];
  });
}

function definedTokens(): Set<string> {
  const css = readFileSync(CSS, "utf8");
  const found = new Set<string>();
  for (const m of css.matchAll(/--color-([a-z]+-\d+)\s*:/g)) found.add(m[1]);
  return found;
}

/** Colour classes only. `shrink-0` and `min-h-0` are not colours, and a naive
 *  scan happily matches the `ink-0` inside `shrink-0`. */
function usedTokens(): Map<string, string[]> {
  const pattern = new RegExp(
    `(?:^|[\\s"'\`:\\[])(?:bg|text|border|ring|fill|stroke|from|to|via|decoration|outline|divide|accent|caret|shadow)-((?:${PALETTES.join("|")})-\\d+)`,
    "g",
  );
  const used = new Map<string, string[]>();
  for (const file of sourceFiles(SRC)) {
    const text = readFileSync(file, "utf8");
    for (const m of text.matchAll(pattern)) {
      const token = m[1];
      used.set(token, [...(used.get(token) ?? []), file]);
    }
  }
  return used;
}

describe("theme tokens", () => {
  it("defines every colour the components actually use", () => {
    const defined = definedTokens();
    const missing = [...usedTokens().entries()]
      .filter(([token]) => !defined.has(token))
      .map(([token, files]) => `${token} (used in ${files.length} file(s))`);
    expect(missing).toEqual([]);
  });

  it("finds tokens at all, so a broken scan cannot pass vacuously", () => {
    const used = usedTokens();
    expect(used.size).toBeGreaterThan(8);
    expect(used.has("ink-900")).toBe(true);
  });

  it("does not mistake shrink-0 for an ink token", () => {
    expect(usedTokens().has("ink-0")).toBe(false);
  });

  // #1494: `bg-accent-500` named a palette outside PALETTES, so the scan above
  // never saw it and the progress fill shipped invisible. This one reads ANY
  // palette name and requires it to be the app's token or Tailwind's own.
  it("resolves every colour class of every palette, not only the app's six", () => {
    const defined = definedColours();
    const missing = sourceFiles(SRC).flatMap((file) =>
      colourClasses(readFileSync(file, "utf8"))
        .filter((token) => !defined.has(token))
        .map((token) => `${token} in ${file.slice(SRC.length + 1)}`));
    expect(missing).toEqual([]);
  });

  it("reads palettes outside the six and skips side widths, so it is not vacuous", () => {
    expect(colourClasses(`className="h-2 bg-accent-500 border-l-4 dark:text-red-500/40 border-l-warn-500"`))
      .toEqual(["accent-500", "red-500", "warn-500"]);
    expect(definedColours().has("signal-500")).toBe(true);
    expect(definedColours().has("amber-400")).toBe(true);
    expect(definedColours().has("accent-500")).toBe(false);
  });
});
