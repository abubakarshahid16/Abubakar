/**
 * The Documents screen groups by discipline.
 *
 * The categorisation existed in the grant tables for days before the screen
 * said anything about it, then said it only as a badge on each card in one
 * flat list ordered by upload date. Grouping is what makes "the IT documents"
 * a thing a reader can see rather than assemble.
 */
import { describe, expect, it } from "vitest";

import { UNCATEGORISED_GROUP, groupByDiscipline } from "./DocumentsView";
import type { DocumentRecord } from "../types/api";

function doc(filename: string, disciplines: string[]): DocumentRecord {
  return {
    id: `doc_${filename}`,
    filename,
    sha256: "a".repeat(64),
    size_bytes: 1,
    page_count: 1,
    pages_done: 1,
    chunk_count: 1,
    chunk_count_total: 1,
    disciplines,
    embedded_count: 1,
    status: "ready",
    needs_ocr_pages: 0,
    recognised_pages: 0,
    equation_pages: 0,
    error: null,
    pages_excluded: 0,
    pages_excluded_characters: 0,
    pages_excluded_with_clause_headings: 0,
    uploaded_at: "2026-09-06T00:00:00Z",
    indexed_at: "2026-09-06T00:00:00Z",
  };
}

const CORPUS = [
  doc("civil-Design-and-Construction.pdf", ["Civil Engineering"]),
  doc("doc20.pdf", ["IT"]),
  doc("doc13.pdf", ["Civil Engineering"]),
  doc("doc17.pdf", ["IT"]),
  doc("NORSOKM501Rev5.pdf", ["Mechanical"]),
  doc("book2-Differential-Equations.pdf", []),
];

describe("grouping the documents by discipline", () => {
  it("puts every IT document together and every Civil document together", () => {
    const groups = groupByDiscipline(CORPUS);
    const names = (n: string) =>
      groups.find((g) => g.name === n)!.documents.map((d) => d.filename);

    expect(names("IT")).toEqual(["doc20.pdf", "doc17.pdf"]);
    expect(names("Civil Engineering")).toEqual([
      "civil-Design-and-Construction.pdf",
      "doc13.pdf",
    ]);
    expect(names("Mechanical")).toEqual(["NORSOKM501Rev5.pdf"]);
  });

  it("gives documents held by no discipline their own named group, last", () => {
    const groups = groupByDiscipline(CORPUS);
    expect(groups[groups.length - 1].name).toBe(UNCATEGORISED_GROUP);
    expect(groups[groups.length - 1].documents.map((d) => d.filename)).toEqual([
      "book2-Differential-Equations.pdf",
    ]);
  });

  it("orders the discipline groups alphabetically, with Admin only pinned last", () => {
    expect(groupByDiscipline(CORPUS).map((g) => g.name)).toEqual([
      "Civil Engineering",
      "IT",
      "Mechanical",
      UNCATEGORISED_GROUP,
    ]);
  });

  /** A grant is many-to-many, so a document held by two disciplines belongs to
   *  both. Showing it once, under whichever sorted first, would tell the other
   *  discipline's reader it was not theirs. */
  it("shows a document under every discipline that holds it", () => {
    const groups = groupByDiscipline([doc("shared.pdf", ["Civil Engineering", "Mechanical"])]);
    expect(groups.map((g) => g.name)).toEqual(["Civil Engineering", "Mechanical"]);
    for (const g of groups) {
      expect(g.documents.map((d) => d.filename)).toEqual(["shared.pdf"]);
    }
  });

  it("keeps every document - grouping hides nothing", () => {
    const shown = new Set(
      groupByDiscipline(CORPUS).flatMap((g) => g.documents.map((d) => d.filename)),
    );
    expect(shown.size).toBe(CORPUS.length);
  });

  it("returns no groups for an empty corpus rather than an empty Admin only group", () => {
    expect(groupByDiscipline([])).toEqual([]);
  });
});
