/**
 * The review screens' status colours come from theme tokens, which are
 * measured in both themes. The pale Tailwind palette classes (rose-200,
 * emerald-300, amber-300, sky-300) are near-white and unreadable on the light
 * theme, so none may come back.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

type Rgb = [number, number, number];
const parseHex = (v: string): Rgb =>
  [0, 2, 4].map((o) => Number.parseInt(v.replace("#", "").slice(o, o + 2), 16) / 255) as Rgb;
const lum = (c: Rgb) => {
  const l = c.map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2];
};
const ratio = (a: Rgb, b: Rgb) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);
const blend = (f: Rgb, b: Rgb, a: number) => f.map((x, i) => x * a + b[i] * (1 - a)) as Rgb;

const css = readFileSync(path.join(process.cwd(), "src", "index.css"), "utf8");
function tokens(selector: string): Record<string, Rgb> {
  const s = css.indexOf(selector);
  const block = css.slice(s, css.indexOf("\n}\n", s));
  return Object.fromEntries(
    [...block.matchAll(/--color-([\w-]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], parseHex(m[2])]),
  );
}

describe("status colour tokens used by the review screens", () => {
  for (const theme of ["light", "dark"] as const) {
    const t = tokens(`:root[data-theme="${theme}"]`);
    it(`are at least 4.5:1 on the card and page surfaces (${theme})`, () => {
      for (const fg of ["danger-500", "warn-500", "info-500", "signal-300"]) {
        for (const bg of ["ink-800", "ink-850", "ink-900"]) {
          expect(t[fg], fg).toBeDefined();
          expect(ratio(t[fg], t[bg]), `${theme} ${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
        }
      }
    });
    it(`stay readable on their own tinted alert fill (${theme})`, () => {
      expect(ratio(t["danger-500"], blend(t["danger-500"], t["ink-850"], 0.1))).toBeGreaterThanOrEqual(4.5);
      expect(ratio(t["signal-300"], blend(t["signal-500"], t["ink-850"], 0.1))).toBeGreaterThanOrEqual(4.5);
    });
  }
});

describe("no pale palette classes on the review screens", () => {
  const files = [
    "views/ReviewRunsView.tsx", "components/review/ReviewDashboardPanel.tsx",
    "components/review/FindingDetail.tsx", "components/review/ReviewCodePanel.tsx",
    "components/review/StandardOverrideControl.tsx", "components/review/CrsCommentControls.tsx",
    "components/review/FindingsTable.tsx",
  ];
  for (const file of files) {
    it(`${file} uses theme tokens only`, () => {
      const source = readFileSync(path.join(process.cwd(), "src", file), "utf8");
      expect(source).not.toMatch(/\b(text|border|bg)-(rose|emerald|amber|sky)-\d{2,3}\b/);
    });
  }
});
