/**
 * STANDING RULE R1 (owner, 27 Nov 2026 03:40: "I don't want previous mistakes to repeat"): a page rebuilt from the shared kit may not
 * style its own title, button, chip, card, table, select, input, notice or colour. This fails the build when a file in KIT_PAGES does.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { KIT_PAGES } from "./kitPages";

const SRC = join(__dirname, "..", "..");

/** What a rebuilt page may not write itself, and the kit part to use instead. */
export const FORBIDDEN: Array<{ what: string; pattern: RegExp; use: string }> = [
  { what: "its own button", pattern: /<button\b/, use: "Button, Tile" },
  { what: "its own title", pattern: /<h1\b/, use: "PageHeader" },
  { what: "its own section heading", pattern: /<h2\b/, use: "SectionTitle or Card title" },
  { what: "its own table", pattern: /<table\b/, use: "Table" },
  { what: "its own select", pattern: /<select\b/, use: "SelectField" },
  { what: "its own text input", pattern: /<input\b(?![^>]*type="(?:checkbox|radio|file)")/, use: "TextField" },
  { what: "its own chip", pattern: /rounded-full/, use: "StatusChip" },
  { what: "its own colour", pattern: /\b(?:bg|text|border)-(?:signal|warn|danger|info|pill-[a-z]+|ok)-\d/, use: "kit parts (the colour comes with them)" },
  { what: "a raw colour value", pattern: /#[0-9a-fA-F]{6}\b|rgba?\(/, use: "kit parts" },
  { what: "an inline style", pattern: /style=\{\{/, use: "kit parts" },
  { what: "mono type", pattern: /\bfont-mono\b/, use: "Small" },
];

export function violations(source: string): string[] {
  return FORBIDDEN.filter((f) => f.pattern.test(source)).map((f) => `${f.what} (use ${f.use})`);
}

describe("a page rebuilt from the shared kit styles nothing itself (R1)", () => {
  it("lists real files", () => {
    for (const file of KIT_PAGES) expect(() => readFileSync(join(SRC, file), "utf8")).not.toThrow();
  });
  for (const file of KIT_PAGES) {
    it(file, () => expect(violations(readFileSync(join(SRC, file), "utf8"))).toEqual([]));
  }
  it("catches each kind of one-off (the rule itself is tested with forged pages)", () => {
    expect(violations('<button className="rounded bg-signal-500">Go</button>')).toEqual(["its own button (use Button, Tile)", "its own colour (use kit parts (the colour comes with them))"]);
    expect(violations("<h1 className=\"text-3xl\">Dashboard</h1>")).toEqual(["its own title (use PageHeader)"]);
    expect(violations('<span className="rounded-full border px-2">Late</span>')).toEqual(["its own chip (use StatusChip)"]);
    expect(violations('<p className="font-mono">refreshed</p>')).toEqual(["mono type (use Small)"]);
    expect(violations('<input type="checkbox" />')).toEqual([]);
    expect(violations('<input value={x} />')).toEqual(["its own text input (use TextField)"]);
    expect(violations("<Button variant=\"primary\">Go</Button>")).toEqual([]);
  });
});
