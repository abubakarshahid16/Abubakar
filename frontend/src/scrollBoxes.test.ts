/**
 * A wide table scrolls inside its own box and never widens the page (26 Nov 2026, measured on a practice copy: at 390 wide the
 * comment sheet's hidden "Actions" header label, `sr-only` and so absolutely placed, escaped its scroll box and made the page 964
 * wide). The rule, for EVERY screen: a box that scrolls sideways (`overflow-x-auto`) around a table that holds a hidden label must
 * be `relative`, so the label is clipped by the box. Read from the source, so a new table is held to it too.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname);

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "node_modules" ? [] : files(path);
    return path.endsWith(".tsx") && !path.endsWith(".test.tsx") ? [path] : [];
  });
}

/** Each scroll box's opening tag and the text up to the end of the first table inside it. A box written as an expression
 *  (`className={on ? "... overflow-x-auto ..." : "..."}`, the new look's way) counts too: EVERY string in it that scrolls must be
 *  relative (26 Nov 2026: a new-look Dashboard box had dropped `relative` in both strings and the literal-only reading missed it). */
function boxes(source: string): { tag: string; inside: string }[] {
  const out: { tag: string; inside: string }[] = [];
  const open = /<div className=(?:"([^"]*\boverflow-x-auto\b[^"]*)"|\{([^{}]*\boverflow-x-auto\b[^{}]*)\})[^>]*>/g;
  for (let m = open.exec(source); m; m = open.exec(source)) {
    const end = source.indexOf("</table>", m.index);
    const nextBox = source.indexOf("overflow-x-auto", m.index + m[0].length);
    if (end < 0 || (nextBox >= 0 && nextBox < end)) continue; // no table of its own
    const tags = m[1] !== undefined ? [m[1]] : [...m[2].matchAll(/"([^"]*)"/g)].map((q) => q[1]).filter((t) => /\boverflow-x-auto\b/.test(t));
    for (const tag of tags) out.push({ tag, inside: source.slice(m.index, end) });
  }
  return out;
}

describe("scroll boxes", () => {
  it("every box that scrolls a table holding a hidden label is relative, so the label never widens the page", () => {
    const wrong: string[] = [];
    for (const path of files(SRC)) {
      for (const box of boxes(readFileSync(path, "utf8"))) {
        if (box.inside.includes("sr-only") && !/\brelative\b/.test(box.tag)) wrong.push(path.slice(SRC.length + 1));
      }
    }
    expect(wrong).toEqual([]);
  });

  it("reads a box written as an expression, string by string", () => {
    const wrong = '<div className={on ? "mt-3 overflow-x-auto" : "relative overflow-x-auto"}><table><th className="sr-only">x</th></table>';
    expect(boxes(wrong).map((b) => /\brelative\b/.test(b.tag))).toEqual([false, true]);
  });

  it("the check sees the three tables it was written for", () => {
    const seen = files(SRC).filter((p) => boxes(readFileSync(p, "utf8")).some((b) => b.inside.includes("sr-only")));
    const names = seen.map((p) => p.split("/").pop());
    for (const name of ["CrsTable.tsx", "FindingsTable.tsx", "ReviewDashboardPanel.tsx"]) expect(names).toContain(name);
  });
});
