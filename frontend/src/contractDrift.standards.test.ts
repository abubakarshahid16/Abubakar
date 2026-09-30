/**
 * Contract drift: the TypeScript mirror of a backend response model must name
 * the fields the backend actually sends.
 *
 * FOUND BY THE 2026-09-30 AUDIT. `StandardRequirement` in contracts/types.ts
 * stopped at phase 3A while the backend model carried every phase-3B field
 * (`requirement_type`, `field`, `operator`, `value`, `unit`, `condition`,
 * `exceptions`, ...), so the Standards Library could not show a structured
 * limit it was already being sent. And `Passage` declared a REQUIRED
 * `highlight` the backend's search `Passage` has never had - a type that
 * promised every search hit a highlight nobody sends.
 *
 * Read from the source files rather than a generated schema so the test runs
 * offline with no backend process. The parse is deliberately narrow: it reads
 * one class / interface body and its field names, and fails loudly when it
 * cannot find the block rather than passing on an empty set.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const REPO = resolve(__dirname, "..", "..");
const SCHEMAS = readFileSync(resolve(REPO, "backend", "app", "schemas.py"), "utf8");
const TYPES = readFileSync(resolve(REPO, "contracts", "types.ts"), "utf8");

function pythonFields(name: string): Set<string> {
  const start = SCHEMAS.indexOf(`\nclass ${name}(BaseModel):`);
  if (start < 0) throw new Error(`backend model ${name} not found`);
  const body = SCHEMAS.slice(start + 1).split("\n").slice(1);
  const end = body.findIndex((line) => /^\S/.test(line));
  const fields = body.slice(0, end < 0 ? undefined : end)
    .map((line) => /^ {4}([a-z_][a-z0-9_]*)\s*:/.exec(line)?.[1])
    .filter((f): f is string => Boolean(f));
  if (fields.length === 0) throw new Error(`no fields read from ${name}`);
  return new Set(fields);
}

function tsFields(name: string): Set<string> {
  const start = TYPES.indexOf(`export interface ${name} {`);
  if (start < 0) throw new Error(`TS interface ${name} not found`);
  const body = TYPES.slice(start).split("\n").slice(1);
  const end = body.findIndex((line) => line.startsWith("}"));
  const fields = body.slice(0, end)
    .map((line) => /^ {2}([a-z_][a-z0-9_]*)\??\s*:/.exec(line)?.[1])
    .filter((f): f is string => Boolean(f));
  if (fields.length === 0) throw new Error(`no fields read from ${name}`);
  return new Set(fields);
}

describe("contract drift: standards and search models", () => {
  it("StandardRequirement names exactly the backend model's fields", () => {
    const backend = [...pythonFields("StandardRequirement")].sort();
    const ts = [...tsFields("StandardRequirement")].sort();
    expect(ts).toEqual(backend);
    // The phase-3B fields the Standards Library renders, named so a failure
    // says which one went missing.
    for (const f of ["requirement_type", "field", "operator", "value", "unit",
                     "raw_value", "raw_unit", "condition", "exceptions"]) {
      expect(ts).toContain(f);
    }
  });

  it("RequirementType lists the backend Literal's values", () => {
    const py = /^RequirementType = Literal\[([^\]]*)\]/m.exec(SCHEMAS)?.[1];
    const tsType = /^export type RequirementType = ([^;]*);/m.exec(TYPES)?.[1];
    expect(py).toBeTruthy();
    expect(tsType).toBeTruthy();
    const values = (s: string) => [...s.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]).sort();
    expect(values(tsType!)).toEqual(values(py!));
  });

  it("Passage declares no field the backend's search Passage does not send", () => {
    const backend = pythonFields("Passage");
    const extra = [...tsFields("Passage")].filter((f) => !backend.has(f));
    // `highlight` lives on AnswerPassage, not on a search hit.
    expect(extra).toEqual([]);
  });
});
