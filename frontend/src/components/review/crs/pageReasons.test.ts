import { describe, expect, it } from "vitest";

import { plainPageReason, unreadPageLine } from "./pageReasons";

describe("unread pages in plain words (order 121 Part B)", () => {
  it("says a page kind as the computer's guess, never as fact", () => {
    const reason = "vision reader: page kind 'cover' (the model's word, unverified); 0 field(s) proposed, 0 proved against the page, 0 recorded, not counted as the page read into fields";
    expect(unreadPageLine(1, reason)).toBe("Page 1 was not fully read: it looks like a cover page (the computer's guess).");
  });

  it("turns each reader's own wording into one short clause", () => {
    expect(plainPageReason("the AI reader timed out on this page")).toBe("the reader ran out of time on it");
    expect(plainPageReason("the AI reader was unavailable (no key)")).toBe("the reader was not available");
    expect(plainPageReason("recognition failed: bad image")).toBe("the scanned text on it could not be recognised");
    expect(plainPageReason("no retrievable chunk covers this page (excluded: boilerplate), so fact extraction never saw it"))
      .toBe("no text could be taken from it");
    expect(plainPageReason("a reader failed on this page (geometry)")).toBe("a reader failed on it");
  });

  it("says only that the page was not fully read when no clause fits, or there is no reason", () => {
    expect(unreadPageLine(7, "something new a reader wrote")).toBe("Page 7 was not fully read.");
    expect(unreadPageLine(3, null)).toBe("Page 3 was not fully read.");
  });

  it("#1550: says each kind of page with no reading (#1473) in plain words", () => {
    expect(unreadPageLine(2, "excluded from the index on purpose (rule page_classified_toc)"))
      .toBe("Page 2 was not read: it was left out on purpose as a table of contents page.");
    expect(unreadPageLine(5, "blank page")).toBe("Page 5 was not read: it is blank.");
    // a reader's own wording is not a page with no reading: unchanged
    expect(unreadPageLine(7, "the AI reader timed out on this page"))
      .toBe("Page 7 was not fully read: the reader ran out of time on it.");
    expect(plainPageReason("excluded from the index on purpose (rule page_classified_references)"))
      .toBe("it was left out on purpose as a references page");
    expect(plainPageReason("set aside by a rule although it holds clause text - not excused (rule page_classified_toc)"))
      .toBe("a rule set it aside although it holds clause text, so it still needs reading");
    expect(plainPageReason("blank page")).toBe("it is blank");
    expect(plainPageReason("image with no reading")).toBe("it is a picture and no reading came back from it");
  });
});
