/** Test helper: the colour names a class may use, and the colour classes a
 *  text names. A colour Tailwind v4 cannot resolve is silent - no error, no
 *  CSS, no effect (#1494: an undefined `accent-500` fill left the progress
 *  bar invisible).
 *  Defined = this app's `@theme` tokens in index.css, plus Tailwind's own
 *  default palette (theme.css), which `@import "tailwindcss"` keeps. */
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC = join(__dirname, "..");

function colourNames(css: string): string[] {
  return [...css.matchAll(/--color-([a-z]+(?:-[a-z]+)*-\d+)\s*:/g)].map((m) => m[1]);
}

/** Every colour token the app's classes can resolve. */
export function definedColours(): Set<string> {
  const own = readFileSync(join(SRC, "index.css"), "utf8");
  const tailwind = readFileSync(join(SRC, "..", "node_modules", "tailwindcss", "theme.css"), "utf8");
  return new Set([...colourNames(own), ...colourNames(tailwind)]);
}

/** Utilities whose argument is a colour. */
const UTILITIES = "bg|text|border|ring|fill|stroke|from|to|via|decoration|outline|divide|accent|caret|shadow|placeholder";

/** Side and axis letters (`border-l-4`, `border-t-2`) are widths, not colours. */
const NOT_COLOURS = new Set(["l", "r", "t", "b", "x", "y", "s", "e", "offset", "opacity"]);

/** The colour tokens ("ink-900", "accent-500") a text's classes name. Variants
 *  (`dark:`, `hover:`), a side (`border-l-`) and an opacity suffix (`/40`) are
 *  allowed around them. */
export function colourClasses(text: string): string[] {
  const pattern = new RegExp(
    `(?:^|[\\s"'\`:\\[!])(?:${UTILITIES})-(?:[lrtbxyse]-(?=[a-z]{2}))?([a-z]+(?:-[a-z]+)*)-(\\d+)(?![\\w-])`, "g");
  return [...text.matchAll(pattern)]
    .filter((m) => !NOT_COLOURS.has(m[1]))
    .map((m) => `${m[1]}-${m[2]}`);
}
