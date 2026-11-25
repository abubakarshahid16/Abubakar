/**
 * IN-PAGE QUESTIONS ONLY (planner, 26 Nov 2026 03:35, item D3): a screen asks the user on the page itself (a `role="alertdialog"`
 * block with its own buttons), never with the browser's own confirm, alert or prompt box, which blocks the page, cannot be styled
 * or tested, and is dropped by some browsers. This reads the frontend source and fails if one comes back.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

// window.confirm(...), globalThis.alert(...), self.prompt(...), and the bare global forms confirm("..."), alert(`...`).
const POPUP = /\b(?:window|globalThis|self)\s*\.\s*(?:confirm|alert|prompt)\s*\(|(?<![.\w$])(?:confirm|alert|prompt)\s*\(\s*["'`]/;

describe("no browser pop-ups", () => {
  it("no frontend source opens the browser's own confirm, alert or prompt box", () => {
    const offenders = sources(join(process.cwd(), "src")).filter((file) =>
      POPUP.test(readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "")));
    expect(offenders).toEqual([]);
  });

  it("the check itself catches every form it names (a forged source)", () => {
    for (const forged of ['window.confirm("x")', "globalThis.alert(1)", "self.prompt('y')", 'confirm("z")', "alert(`w`)"]) {
      expect(POPUP.test(forged)).toBe(true);
    }
    for (const fine of ["void confirm(row)", "reviewsApi.confirm(id)", "classification.confirm(doc.id, {})"]) {
      expect(POPUP.test(fine)).toBe(false);
    }
  });
});
