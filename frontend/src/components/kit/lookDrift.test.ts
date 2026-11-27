/**
 * LOOK-KIT DRIFT RATCHET (owner, 27 Nov 2026 12:47: "one table style, one card style, one notice style everywhere; a test that fails
 * if a page invents a new one"). Builder C.
 *
 * Every .tsx and .ts under src/ (not tests, not the kit itself) is read as text and three kinds of hand-made style are counted per file:
 *   TABLE  - a <table> whose tag names no kit table class (kit-table / kit-stack-table);
 *   CARD   - a class string with rounded + border + a background, that is no kit part (kit-card / kit-row-btn / kit-tile / kit-notice);
 *   NOTICE - a class string with a tinted warning / problem / info / signal background (e.g. bg-warn-500/10), that is not kit-notice.
 * Today's counts are the baseline in lookDriftBaseline.json. A file may never go UP (new drift fails CI from day one, the message names
 * the kit part to use), and a NEW file must be 0. When a cleanup brings a count DOWN, this test asks for the baseline to be lowered in
 * the same PR, so the ratchet only ever tightens. Regenerate after a cleanup:  LOOK_DRIFT_WRITE=1 npx vitest run lookDrift
 */
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..", "..");
const BASELINE = join(__dirname, "lookDriftBaseline.json");

export type Kind = "table" | "card" | "notice";
export const USE: Record<Kind, string> = { table: "the kit Table (or kit-stack-table)", card: "the kit Card", notice: "the kit Notice" };

const KIT_TABLE = /\bkit-(?:stack-)?table\b/;
const KIT_PART = /\bkit-(?:card|row-btn|tile|notice|stack-table|table|tag|chip|btn)\b/;

/** The class strings of a source file: every "..." and `...` literal. The standard both-looks pattern
 *  `NEW_LOOK ? "kit-..." : "classic classes"` draws only the kit part in the new look, so the else-branch of a ternary whose first
 *  string names a kit part is NOT counted (H's read of #2010: it failed every new file written with a classic fallback). */
function classStrings(source: string): string[] {
  // ONLY a NEW_LOOK ternary (F's gate: any `x ? "kit-tag" : "<one-off card>"` hid the card), in both orders (H's note (a)):
  //   NEW_LOOK ? "kit-..." : "classic"   and   !NEW_LOOK ? "classic" : "kit-..."
  const S = '("[^"\\n]*"|`[^`]*`)';
  const kitElse = source
    .replace(new RegExp(`(?<![!\\w.])NEW_LOOK\\s*\\?\\s*${S}\\s*:\\s*${S}`, "g"), (whole, first: string) => (KIT_PART.test(first) ? `NEW_LOOK ? ${first} : ""` : whole))
    .replace(new RegExp(`!\\s*NEW_LOOK\\s*\\?\\s*${S}\\s*:\\s*${S}`, "g"), (whole, _first: string, second: string) => (KIT_PART.test(second) ? `!NEW_LOOK ? "" : ${second}` : whole));
  const out: string[] = [];
  for (const m of kitElse.matchAll(/"([^"\n]{3,})"|`([^`]{3,})`/g)) out.push(m[1] ?? m[2]);
  return out;
}

export function drift(source: string): Record<Kind, number> {
  const table = [...source.matchAll(/<table\b[^>]*>/g)].filter((m) => !KIT_TABLE.test(m[0])).length;
  const strings = classStrings(source);
  // a card: rounded + a background + an edge, the edge a border OR a shadow (H: ReviewCrsList's own section used a shadow)
  const card = strings.filter((s) => /\brounded\b|\brounded-\[|\brounded-(?:sm|md|lg|xl)\b/.test(s) && /\bbg-(?:ink|white|slateish)/.test(s)
    && (/\bborder(?:\s|$|")|\bborder-(?:ink|white|slateish)-/.test(s) || /\bshadow-/.test(s)) && !KIT_PART.test(s)).length;
  // a notice: a tinted warning/problem/info/signal fill (number or bracket opacity), OR a coloured edge with padding (a left-bar notice)
  const TINT = /\bbg-(?:warn|danger|info|signal|check|ok)-\d{2,3}\/(?:\d+|\[[\d.]+\])/;
  const EDGE = /\bborder-(?:l-\d+\s.*)?(?:warn|danger|info|signal|check|ok)-\d{2,3}\b|\bborder-l-\d+\b.*\bborder-(?:warn|danger|info|signal|check|ok)-\d{2,3}/;
  const notice = strings.filter((s) => (TINT.test(s) || (EDGE.test(s) && /\bp[xy]?-\d/.test(s))) && !/\bkit-notice\b/.test(s)).length;
  return { table, card, notice };
}

function files(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) { if (name !== "node_modules") out.push(...files(p)); continue; }
    // .tsx pages and .ts helpers (tone or format maps hold class strings too; H's read of #2010)
    if (!/\.tsx?$/.test(name) || /\.(test|spec)\.tsx?$/.test(name) || name.endsWith(".d.ts")) continue;
    out.push(p);
  }
  return out;
}

function measure(): Record<string, Record<Kind, number>> {
  const res: Record<string, Record<Kind, number>> = {};
  for (const p of files(SRC)) {
    const rel = relative(SRC, p).split("\\").join("/");
    if (rel.startsWith("components/kit/")) continue; // the kit IS the style
    const d = drift(readFileSync(p, "utf8"));
    if (d.table || d.card || d.notice) res[rel] = d;
  }
  return Object.fromEntries(Object.entries(res).sort(([a], [b]) => a.localeCompare(b)));
}

describe("look-kit drift ratchet: one table, card and notice style (owner, 27 Nov 2026)", () => {
  const now = measure();
  if (process.env.LOOK_DRIFT_WRITE) writeFileSync(BASELINE, JSON.stringify(now, null, 1) + "\n");
  const baseline: Record<string, Partial<Record<Kind, number>>> = JSON.parse(readFileSync(BASELINE, "utf8"));

  it("no file draws MORE hand-made tables, cards or notices than its baseline (a new file: none)", () => {
    const up: string[] = [];
    for (const [file, d] of Object.entries(now)) {
      for (const kind of ["table", "card", "notice"] as Kind[]) {
        const was = baseline[file]?.[kind] ?? 0;
        if (d[kind] > was) up.push(`${file}: ${d[kind] - was} new hand-made ${kind}${d[kind] - was === 1 ? "" : "s"} (${was} -> ${d[kind]}); use ${USE[kind]}`);
      }
    }
    expect(up, `look drift went UP:\n${up.join("\n")}`).toEqual([]);
  });

  it("the baseline is tight: a cleanup lowers it in the same PR (LOOK_DRIFT_WRITE=1 npx vitest run lookDrift)", () => {
    const down: string[] = [];
    for (const [file, was] of Object.entries(baseline)) {
      for (const kind of ["table", "card", "notice"] as Kind[]) {
        const n = now[file]?.[kind] ?? 0;
        if ((was[kind] ?? 0) > n) down.push(`${file}: ${kind} ${was[kind]} -> ${n}`);
      }
    }
    expect(down, `well done, the drift went DOWN; lower the baseline:\n${down.join("\n")}`).toEqual([]);
  });

  it("each detector catches its kind and passes the kit's own part (planted cases)", () => {
    expect(drift('<table className="w-full text-left text-sm">')).toEqual({ table: 1, card: 0, notice: 0 });
    expect(drift('<table className={NEW_LOOK ? "kit-stack-table w-full" : "w-full"}>')).toEqual({ table: 0, card: 0, notice: 0 });
    expect(drift('<div className="rounded border border-ink-700 bg-ink-850 p-3">')).toEqual({ table: 0, card: 1, notice: 0 });
    expect(drift('<div className="kit-card">')).toEqual({ table: 0, card: 0, notice: 0 });
    expect(drift('<p className="rounded bg-warn-500/10 px-3 py-2 text-warn-500">')).toEqual({ table: 0, card: 0, notice: 1 });
    expect(drift('<div className="kit-notice kit-notice--warn">')).toEqual({ table: 0, card: 0, notice: 0 });
    // the both-looks pattern: the classic branch of a kit ternary is not drift (H)
    expect(drift('<div className={NEW_LOOK ? "kit-card" : "rounded border border-ink-700 bg-ink-850 p-3"}>')).toEqual({ table: 0, card: 0, notice: 0 });
    expect(drift('<div className={NEW_LOOK ? "p-2" : "rounded border border-ink-700 bg-ink-850 p-3"}>')).toEqual({ table: 0, card: 1, notice: 0 });
    // only a NEW_LOOK ternary hides its classic branch: any other condition never hides a one-off (F's planted case 6)
    expect(drift('<span className={open ? "kit-tag" : "rounded-md border border-ink-700 bg-ink-850 p-3"}>')).toEqual({ table: 0, card: 1, notice: 0 });
    // the reversed order, classic first (H's note (a))
    expect(drift('<div className={!NEW_LOOK ? "rounded border border-ink-700 bg-ink-850 p-3" : "kit-card"}>')).toEqual({ table: 0, card: 0, notice: 0 });
    // H's slip-throughs: a shadow card, a left-bar notice, a bracket-opacity tint
    expect(drift('<section className="rounded-[var(--radius-md)] bg-ink-800 p-5 shadow-[var(--shadow-resting)]">')).toEqual({ table: 0, card: 1, notice: 0 });
    expect(drift('<div className="border-l-4 border-warn-500 px-3 py-2 text-sm">')).toEqual({ table: 0, card: 0, notice: 1 });
    expect(drift('<p className="rounded bg-warn-500/[0.08] px-3 py-2">')).toEqual({ table: 0, card: 0, notice: 1 });
  });
});
