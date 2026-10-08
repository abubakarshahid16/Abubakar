/**
 * The comparison card, honesty pass (2026-10-01, audit entry 99): a side's
 * markdown is laid out like the ordinary answer's, every in-text citation
 * number opens the source of the same number, and "Not found in the pages
 * read" is shown only for a side whose own search ran.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AnswerCard, type AnswerView } from "./AnswerCard";
import type { AnswerPassage } from "../../types/api";

function passage(doc: string, page: number): AnswerPassage {
  return {
    chunk_id: `${doc}:${page}`,
    document_id: doc,
    filename: `${doc}.pdf`,
    page_start: page,
    page_end: page,
    section: null,
    text: `text ${doc} ${page}`,
    highlight: null,
    match_span: null,
    chunks_joined: 1,
    kind: "prose",
    score: 1,
    identifier_hits: [],
    text_source: "extracted",
    ocr_min_conf: null,
    ocr_alphabet_violations: 0,
    ocr_alphabet_sample: null,
  };
}

function view(over: Partial<AnswerView>, sides: NonNullable<AnswerView["comparison"]>["sides"], passages: AnswerPassage[]): AnswerView {
  return {
    answer_type: "comparison",
    answer: "",
    reason: null,
    passage: null,
    supporting: [],
    passages,
    cited: [],
    rejected_citations: [],
    model: null,
    truncated: false,
    evidence_removed: [],
    seconds: 1,
    examples: [],
    comparison: { sides },
    ...over,
  };
}

const NOT_FOUND_A = {
  name: "STD-A-001",
  document_ids: ["doc-a"],
  answer_type: "insufficient_evidence",
  text: "STD-A-001: not found in the pages read.",
  source_start: 0,
  source_count: 0,
  searched: true,
};

describe("a side's markdown is rendered, not shown as raw marks", () => {
  const bullets = "- **Preheat** is required [S1].\n- Hold time applies [S2].";
  const v = view(
    {},
    [
      NOT_FOUND_A,
      {
        name: "STD-B-002",
        document_ids: ["doc-b"],
        answer_type: "generated",
        text: bullets,
        source_start: 0,
        source_count: 2,
        searched: true,
      },
    ],
    [passage("doc-b", 4), passage("doc-b", 5)],
  );

  it("lays bullets out as list items and bold as strong, with no raw asterisks", () => {
    const { container } = render(<AnswerCard view={v} onSelectSource={() => {}} activeSource={null} />);
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("strong")).toHaveTextContent("Preheat");
    expect(container.textContent).not.toContain("**");
    expect(container.textContent).not.toMatch(/(^|\s)-\s\w/);
  });

  it("an in-text citation opens the source of the same number", async () => {
    const onSelect = vi.fn();
    render(<AnswerCard view={v} onSelectSource={onSelect} activeSource={null} />);
    await userEvent.click(screen.getByRole("button", { name: "Source 2" }));
    expect(onSelect).toHaveBeenCalledWith(1);
    expect(v.passages[1].page_start).toBe(5);
  });
});

describe("citation numbers on the second side are the global numbers", () => {
  it("side B citing [S3] and [S12] opens passages 3 and 12 (indexes 2 and 11)", async () => {
    const passages = [
      ...Array.from({ length: 2 }, (_, i) => passage("doc-a", i + 1)),
      ...Array.from({ length: 10 }, (_, i) => passage("doc-b", i + 1)),
    ];
    const v = view(
      {},
      [
        {
          name: "STD-A-001",
          document_ids: ["doc-a"],
          answer_type: "generated",
          text: "Alpha [S1].",
          source_start: 0,
          source_count: 2,
          searched: true,
        },
        {
          name: "STD-B-002",
          document_ids: ["doc-b"],
          answer_type: "generated",
          text: "Bravo [S3] and [S12].",
          source_start: 2,
          source_count: 10,
          searched: true,
        },
      ],
      passages,
    );
    const onSelect = vi.fn();
    render(<AnswerCard view={v} onSelectSource={onSelect} activeSource={null} />);
    await userEvent.click(screen.getAllByRole("button", { name: "Source 3" })[0]);
    await userEvent.click(screen.getByRole("button", { name: "Source 12" }));
    expect(onSelect).toHaveBeenNthCalledWith(1, 2);
    expect(onSelect).toHaveBeenNthCalledWith(2, 11);
    expect(passages[2].document_id).toBe("doc-b");
    expect(passages[11].document_id).toBe("doc-b");
  });
});

describe("not found is only said for a side that was searched", () => {
  it("says not found for a searched, empty side", () => {
    const v = view({}, [NOT_FOUND_A], []);
    render(<AnswerCard view={v} onSelectSource={() => {}} activeSource={null} />);
    expect(screen.getByText(/Not found in the pages read\./)).toBeInTheDocument();
  });

  it("says not among the documents you can read for a side that was never searched", () => {
    const v = view({}, [{ ...NOT_FOUND_A, searched: false }], []);
    render(<AnswerCard view={v} onSelectSource={() => {}} activeSource={null} />);
    expect(screen.queryByText(/Not found in the pages read/)).toBeNull();
    expect(screen.getByText(/Not among the documents you can read/)).toBeInTheDocument();
  });
});
