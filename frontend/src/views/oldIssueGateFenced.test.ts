/**
 * Order 121 Part A: from the comment sheet and everything it links to, no
 * path reaches the old issue gate (one line per raw finding, "Item 149 has
 * no engineer's decision", engine notes in the open). The review is signed
 * on the sheet's "Before you sign" box only.
 *
 * The screens under /review/:id are the comment sheet, the card view and its
 * behind-the-scenes pages; this reads every source file of the app and fails
 * if the old panel, or its per-finding sentence, comes back anywhere.
 */
import { describe, expect, it } from "vitest";

const sources = import.meta.glob(["/src/**/*.ts", "/src/**/*.tsx", "!/src/**/*.test.ts", "!/src/**/*.test.tsx"], {
  query: "?raw", import: "default", eager: true,
}) as Record<string, string>;

describe("the old issue gate is fenced off (order 121)", () => {
  it("reads the app's sources (not vacuous)", () => {
    const names = Object.keys(sources);
    expect(names.some((n) => n.endsWith("views/CrsSheetView.tsx"))).toBe(true);
    expect(names.some((n) => n.endsWith("panels/BehindTheScenes.tsx"))).toBe(true);
    expect(names.length).toBeGreaterThan(50);
  });

  it("no screen renders the old gate panel or its per-finding line", () => {
    const offenders = Object.entries(sources)
      .filter(([, text]) => /CrsIssueGatePanel|has no engineer's decision|Not ready to issue to the contractor/.test(text))
      .map(([name]) => name);
    expect(offenders).toEqual([]);
  });

  // ONE issuing path (order 121, #1158): the contractor's copy is asked for
  // in exactly one file, crs/issueContractorCopy.ts, which applies the
  // comment sheet's "Before you sign" rules; only the comment sheet and the
  // new workspace's sign-off call it. Every other export is the internal
  // working copy, spelled out as a literal "internal" so no variable can
  // carry "issue" past this check.
  const ISSUER = "src/components/review/crs/issueContractorCopy.ts";

  /** Every call `name(first, second...)` in a file, with its second argument
   *  as written (a definition `function name(...)` is not a call). */
  function secondArgs(text: string, name: string): string[] {
    const out: string[] = [];
    const call = new RegExp(`(?<!function )\\b${name}\\(([^()]*)\\)`, "g");
    for (const m of text.matchAll(call)) {
      const args = m[1].split(",").map((a) => a.trim());
      out.push(args[1] ?? "");
    }
    return out;
  }

  it("only one file asks for the contractor's copy, through downloadCrs, and it asks for it once", () => {
    const issuers: string[] = [];
    const others: string[] = [];
    for (const [name, text] of Object.entries(sources)) {
      const file = name.replace(/^\//, "");
      for (const arg of secondArgs(text, "downloadCrs")) {
        if (arg === '"issue"') issuers.push(file);
        else if (arg !== '"internal"') others.push(`${file}: downloadCrs(..., ${arg || "nothing"})`);
      }
    }
    expect(issuers).toEqual([ISSUER]);
    expect(others).toEqual([]);
  });

  it("the server's export route is reached only through downloadCrs (or for the internal copy)", () => {
    const offenders: string[] = [];
    for (const [name, text] of Object.entries(sources)) {
      const file = name.replace(/^\//, "");
      if (file === "src/api/review.ts" || file === "src/components/review/downloadCrs.ts") continue;
      // No second argument = the API's default, the internal copy.
      for (const arg of secondArgs(text, "exportCrs")) if (arg && arg !== '"internal"') offenders.push(`${file}: exportCrs(..., ${arg})`);
    }
    expect(offenders).toEqual([]);
  });

  it("only the comment sheet and the workspace sign-off issue the contractor's copy, both through the shared path", () => {
    const callers = Object.entries(sources)
      .map(([name, text]) => [name.replace(/^\//, ""), text] as const)
      .filter(([file, text]) => file !== ISSUER && /\bissueContractorCopy\(/.test(text))
      .map(([file]) => file)
      .sort();
    expect(callers).toEqual(["src/components/review/workspace/useSignOff.ts", "src/views/CrsSheetView.tsx"]);
    // The shared path applies the issue gate itself (it is not just a rename
    // of downloadCrs): it refuses while anything is left.
    expect(sources[`/${ISSUER}`]).toMatch(/issueWaitsFor\(checks\)/);
    expect(sources[`/${ISSUER}`]).toMatch(/signLeft/);
  });

  // The workspace's confirm step (#1168): "Issue to contractor" reaches the
  // issuer through `issueConfirmed(runId)`, exported by useSignOff.ts, which
  // runs the on-screen sign-off's issuer with its live checks. Only the
  // confirm step may use it; any other file naming it in code (a call, an
  // import, a renamed import) would be a second way to issue.
  const CONFIRMED_HOME = "src/components/review/workspace/useSignOff.ts";

  /** The file's text with comments taken out, so a mention in a comment
   *  is not a use. */
  function code(text: string): string {
    return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
  }

  it("only the confirm step calls issueConfirmed, and it is defined in the workspace sign-off", () => {
    expect(code(sources[`/${CONFIRMED_HOME}`])).toMatch(/export async function issueConfirmed\(/);
    expect(code(sources[`/${CONFIRMED_HOME}`])).toMatch(/issueContractorCopy\(runId, checks\(\)\)/);
    const users = Object.entries(sources)
      .map(([name, text]) => [name.replace(/^\//, ""), code(text)] as const)
      .filter(([file, text]) => file !== CONFIRMED_HOME && /\bissueConfirmed\b/.test(text))
      .map(([file]) => file)
      .sort();
    expect(users).toEqual(["src/components/review/workspace/sign/SignConfirm.tsx"]);
  });
});
