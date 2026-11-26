import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { NAV } from "./components/Shell";

describe("the new look (owner, 26 Nov 2026): style only, the same app", () => {
  it("is off unless VITE_UI_NEW_LOOK is true, and every rule applies only under data-look=new", () => {
    // the switch has ONE home (look.ts, owner's Dashboard notes): App stamps data-look from it, the folded parts read it there
    const home = readFileSync(path.resolve(__dirname, "look.ts"), "utf8");
    expect(home).toMatch(/import\.meta\.env\.VITE_UI_NEW_LOOK === "true"/);
    const app = readFileSync(path.resolve(__dirname, "App.tsx"), "utf8");
    expect(app).toMatch(/import \{ NEW_LOOK \} from "\.\/look";/);
    expect(app).not.toMatch(/import\.meta\.env\.VITE_UI_NEW_LOOK/);
    const look = readFileSync(path.resolve(__dirname, "look.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    const selectors = look.split("}").map((block) => block.split("{")[0].trim()).filter(Boolean);
    expect(selectors.length).toBeGreaterThan(3);
    for (const selector of selectors) {
      for (const part of selector.split(",")) expect(part.trim()).toMatch(/^:root\[data-look="new"\]/);
    }
  });

  it("keeps all the menu items and their names (no structure change)", () => {
    expect(NAV.map((item) => item.label)).toEqual([
      "Dashboard", "AI Submittal Review", "Documents", "Standards Library", "Analysis Hub", "Chat", "CRS & Reports",
      "Deliverables", "Ingestion", "Technical Queries and CFCs",
    ]);
  });
});
