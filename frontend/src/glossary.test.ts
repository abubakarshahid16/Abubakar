/**
 * The words the UI is allowed to use.
 *
 * `docs/ui-glossary.md` fixes one term per concept so two screens never name
 * the same thing differently: Deliverable, Owner, Reviewer.
 *
 * "SUBMITTAL" WAS BANNED AND IS NOW ALLOWED, and the reason is that the ban
 * outlived its subject. It was written against the DELIVERABLES vocabulary -
 * "a tracked engineering output is a Deliverable, not a submittal or an item"
 * - and it was right about that. It then collided with a different thing
 * entirely: the AI Submittal Review workflow (CLAUDE.md rule 10, master plan
 * section 16), whose name contains the word, whose navigation entry reads "AI
 * Submittal Review", and whose whole subject is a contractor's submittal -
 * a document somebody sends for review, which is not a deliverable being
 * tracked.
 *
 * So the test was failing on `Shell.tsx` for saying the product's own name.
 * A rule that forbids the product from naming itself is a rule that has
 * stopped describing the product, and the honest fix is to narrow the rule
 * rather than to rename the feature or to leave a permanently red test.
 *
 * EVERY OTHER TERM STAYS BANNED, and the old client name is added: CLAUDE.md
 * rule on naming says the old names "must not appear in code, docs or UI",
 * and until now nothing checked it.
 */
import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

/**
 * Terms that must not reach a reader.
 *
 * `submittal` is deliberately NOT here; see the note above.
 */
const BANNED = /\b(assignee|checker|nabaa)\b/i;

/** Where rendered text lives. */
const ROOTS = ["views", "components"];

function sourcesUnder(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      out.push(...sourcesUnder(path));
      continue;
    }
    // Tests are excluded: a test may legitimately name a banned term in
    // order to assert it is absent, which is this file doing exactly that.
    if (/\.(tsx|ts)$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      out.push(path);
    }
  }
  return out;
}

describe("UI terminology", () => {
  const root = resolve(__dirname);
  const files = ROOTS.flatMap((name) => sourcesUnder(resolve(root, name)));

  it("scans the source that actually renders text", () => {
    // THE GUARD ON THE GUARD. A scan whose file list quietly became empty
    // would pass forever while checking nothing - the shape recorded as
    // entry 14 of the honesty audit.
    expect(files.length).toBeGreaterThan(30);
  });

  it.each(["components/Shell.tsx"])(
    "%s may name the product's own workflow", (relative) => {
      const source = readFileSync(resolve(root, relative), "utf8");

      expect(source).toMatch(/AI Submittal Review/);
      expect(source).not.toMatch(BANNED);
    },
  );

  it("does not reintroduce banned synonyms in rendered source strings", () => {
    const offenders = files
      .filter((path) => BANNED.test(readFileSync(path, "utf8")))
      .map((path) => path.slice(root.length + 1));

    expect(offenders).toEqual([]);
  });
});
