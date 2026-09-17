import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

describe("UI terminology", () => {
  it("does not reintroduce banned synonyms in rendered source strings", () => {
    const root = resolve(__dirname);
    const source = readFileSync(resolve(root, "components/Shell.tsx"), "utf8");
    expect(source).not.toMatch(/\b(submittal|assignee|checker)\b/i);
  });
});
