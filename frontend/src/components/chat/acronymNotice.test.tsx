/**
 * #615: an answer given before some documents' abbreviation maps were built
 * says so; a complete map, or an older answer with no record, says nothing.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { acronymNote, viewFromMessage } from "./AnswerCardContent";
import { AnswerCard } from "./AnswerCardView";
import type { Message } from "../../types/api";

function message(acronym_map: unknown): Message {
  return {
    id: "m1", role: "assistant", text: "Not found in the documents.",
    answer_type: "insufficient_evidence", reason: "no passage", created_at: "2026-10-18T00:00:00Z",
    payload: { acronym_map },
  } as unknown as Message;
}

describe("the abbreviation notice (#615)", () => {
  it("names how many documents' abbreviations were not used, with what to do", () => {
    expect(acronymNote({ documents_not_ready: 3, complete: false })).toMatch(
      /^Abbreviations defined in 3 documents were not used for this answer.*Ask again in a minute/);
    expect(acronymNote({ documents_not_ready: 1, complete: false })).toMatch(/in 1 document were/);
  });

  it("says nothing for a complete map or an answer with no record, never 0", () => {
    expect(acronymNote({ documents_not_ready: 0, complete: true })).toBeNull();
    expect(acronymNote(null)).toBeNull();
    expect(acronymNote(undefined)).toBeNull();
  });

  it("is shown on the answer card, and survives a reopened conversation", () => {
    const view = viewFromMessage(message({ documents_not_ready: 2, complete: false }));
    render(<AnswerCard view={view} onSelectSource={() => undefined} activeSource={null} />);
    expect(screen.getByTestId("acronym-notice").textContent).toContain("2 documents");
  });

  it("is absent from an answer whose map was complete", () => {
    render(<AnswerCard view={viewFromMessage(message({ documents_not_ready: 0, complete: true }))} onSelectSource={() => undefined} activeSource={null} />);
    expect(screen.queryByTestId("acronym-notice")).toBeNull();
  });
});
