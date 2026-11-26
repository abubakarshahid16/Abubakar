/**
 * A grid of fixed-width columns switches on only where the screen has room for it (26 Nov 2026, the auditor's live walk: the
 * Deliverables page was 1,038 wide on a 758 screen, because three grids of fixed columns, 530 px and more before their text column,
 * switched on at `md`, where the page beside the menu is far narrower). Measured after the fix on a practice copy at 390, 768, 1024,
 * 1280 and 1440: the page is never wider than the screen. The rule, for EVERY screen, read from the source: the fixed pixel columns
 * of a `grid-cols-[...]` may add up to at most ROOM[breakpoint]; a wider grid waits for a wider breakpoint (it stacks before it).
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname);
//: The fixed pixels a grid may hold at each breakpoint, leaving room for its text column, the menu and the page's padding.
const ROOM: Record<string, number> = { "": 300, sm: 300, md: 300, lg: 500, xl: 900, "2xl": 1200 };

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "node_modules" ? [] : files(path);
    return path.endsWith(".tsx") && !path.endsWith(".test.tsx") ? [path] : [];
  });
}

function grids(source: string): { at: string; px: number; text: string }[] {
  const out: { at: string; px: number; text: string }[] = [];
  const grid = /(?:(sm|md|lg|xl|2xl):)?grid-cols-\[([^\]]+)\]/g;
  for (let m = grid.exec(source); m; m = grid.exec(source)) {
    const px = [...m[2].matchAll(/(?:^|_)(\d+)px(?=_|$)/g)].reduce((sum, p) => sum + Number(p[1]), 0);
    out.push({ at: m[1] ?? "", px, text: m[0] });
  }
  return out;
}

describe("grid widths", () => {
  it("no grid of fixed columns switches on before the screen has room for it", () => {
    const wrong: string[] = [];
    for (const path of files(SRC)) {
      for (const g of grids(readFileSync(path, "utf8"))) {
        if (g.px > ROOM[g.at]) wrong.push(`${path.slice(SRC.length + 1)}: ${g.text} (${g.px} px fixed)`);
      }
    }
    expect(wrong).toEqual([]);
  });

  it("the check reads the Deliverables grids it was written for", () => {
    const found = grids(readFileSync(join(SRC, "views", "DeliverablesView.tsx"), "utf8"));
    expect(found.map((g) => g.px).sort((a, b) => a - b)).toEqual([380, 420, 460, 530]); // 420: the new look's register row (one status)
    expect(grids("md:grid-cols-[130px_1fr_180px_150px_auto]")[0]).toMatchObject({ at: "md", px: 460 }); // the old form grid: too wide at md
  });
});
