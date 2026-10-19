import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReasonText } from "./ReasonText";
import { REASON_CODE_WORDS, SENSE_CHECK_RULE, isSenseCheck, splitReason } from "./reasonWords";

describe("reason words (order 120 item 3)", () => {
  it("splits a known code off and gives its sentence", () => {
    const split = splitReason("no_field_matched: no field read from this datasheet was named");
    expect(split.code).toBe("no_field_matched");
    expect(split.words).toBe(REASON_CODE_WORDS.no_field_matched);
    expect(split.rest).toBe("no field read from this datasheet was named");
    expect(splitReason("UNREAD_PAGES: pages 4, 9").code).toBe("UNREAD_PAGES");
  });

  it("never takes a plain word or acronym for a code", () => {
    for (const text of ["PSV: set pressure 10 barg", "Note: see page 2", "Set pressure is blank"]) {
      expect(splitReason(text)).toEqual({ code: null, words: "", rest: text });
    }
  });

  it("shows the sentence and the rest, the code only in the tooltip", () => {
    render(<p data-testid="t"><ReasonText text="ambiguous_match: two fields are named" /></p>);
    const shown = screen.getByTestId("t");
    expect(shown).toHaveTextContent(`${REASON_CODE_WORDS.ambiguous_match} two fields are named`);
    expect(shown).not.toHaveTextContent("ambiguous_match");
    expect(shown.querySelector("[title]")?.getAttribute("title")).toContain("ambiguous_match");
  });

  it("a code the table does not name is still hidden, its words kept", () => {
    render(<p data-testid="t"><ReasonText text="some_new_code: the value was odd" /></p>);
    expect(screen.getByTestId("t")).toHaveTextContent(/^the value was odd$/);
  });

  it("an AI check with no standard is the computer's sense check; one with a clause is not", () => {
    expect(isSenseCheck({ origin: "ai_engineering_check", standard_document_id: null, standard_clause: null })).toBe(true);
    expect(isSenseCheck({ origin: "ai_engineering_check", standard_document_id: null, standard_clause: "4.1" })).toBe(false);
    expect(isSenseCheck({ origin: null, standard_document_id: null, standard_clause: null })).toBe(false);
    expect(SENSE_CHECK_RULE).toMatch(/sense check/);
  });
});
