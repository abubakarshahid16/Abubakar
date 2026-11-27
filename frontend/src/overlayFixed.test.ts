/** A drawer or dialog placed in a page's aurora field stays a FIXED overlay (H's audit, 27 Nov 2026: /documents/<id> opened its preview at
 *  the bottom of a 21,000px page because the field's "children are relative" rule beat Tailwind's `fixed`). */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("the aurora field never un-fixes an overlay", () => {
  it("leaves .fixed children out of its position: relative rule", () => {
    const css = readFileSync(join(__dirname, "index.css"), "utf8");
    const rules = [...css.matchAll(/\.aurora-field\s*>\s*([^{]+)\{([^}]*)\}/g)].filter((m) => /position:\s*relative/.test(m[2]));
    expect(rules.length).toBeGreaterThan(0);
    for (const m of rules) expect(m[1]).toContain(":not(.fixed)");
  });
});
