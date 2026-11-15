/**
 * THE ONE START (owner, 12 Nov 2026, #1584): every start a user can reach shows the list of documents that will leave the Mac first and
 * goes through `POST /api/reviews/start`. The old one-click start (`reviewsApi.startReviewRun` -> `POST /api/reviews/run`) has no caller:
 * this reads the frontend source and fails if one comes back.
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

describe("the one start", () => {
  it("no frontend source calls the old one-click start or its route", () => {
    const offenders = sources(join(process.cwd(), "src")).filter((file) => {
      const text = readFileSync(file, "utf8");
      return /startReviewRun/.test(text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "")) || /["'`]\/reviews\/run["'`]/.test(text);
    });
    expect(offenders).toEqual([]);
  });

  it("the only start route the frontend posts to is /reviews/start", () => {
    const posts = sources(join(process.cwd(), "src")).flatMap((file) =>
      [...readFileSync(file, "utf8").matchAll(/["'`]\/reviews\/(?:start|run)["'`]/g)].map((m) => `${file}:${m[0]}`),
    );
    expect(posts.every((p) => p.endsWith('"/reviews/start"'))).toBe(true);
    expect(posts.length).toBeGreaterThan(0);
  });

  it("no frontend source posts to the AI review's own start route or calls its client function (the one start is /reviews/start)", () => {
    const offenders = sources(join(process.cwd(), "src")).filter((file) => {
      const text = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
      return /["'`]\/reviews\/agent-run["'`]/.test(text) || /agentReview\.start\b/.test(text);
    });
    expect(offenders).toEqual([]);
  });
});
