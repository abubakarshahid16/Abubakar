/**
 * #925 items 2 and 3 (A11): one <main> landmark per page, owned by the
 * Shell, and no control smaller than 12 px. Source-level guards: each fails
 * the moment a view grows its own <main> or a control its own 11 px class.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");

function read(rel: string): string {
  return readFileSync(join(SRC, rel), "utf8");
}

describe("A11 guards", () => {
  it("only the Shell (and the sign-in page outside it) renders a <main>", () => {
    const offenders = readdirSync(join(SRC, "views"))
      .filter((f) => f.endsWith(".tsx") && !f.includes(".test.") && f !== "LoginView.tsx")
      .filter((f) => /<main[\s>]/.test(read(join("views", f))));
    expect(offenders).toEqual([]);
    expect((read("components/Shell.tsx").match(/<main[\s>]/g) ?? []).length).toBe(1);
  });

  it("no review control uses an 11 px font", () => {
    const dir = join(SRC, "components", "review");
    const offenders = readdirSync(dir)
      .filter((f) => f.endsWith(".tsx") && !f.includes(".test."))
      .filter((f) => /text-\[11px\]/.test(read(join("components", "review", f))));
    expect(offenders).toEqual([]);
  });
});
