/**
 * #1017: a page ledger nobody has built is said on the strip, with no count
 * in its place - the read never rebuilds it.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ReviewReadiness } from "../../types/api";
import { ReadinessStrip } from "./ReadinessStrip";

vi.mock("../../api/client", () => ({
  reviews: { visionReaderStatus: () => new Promise(() => {}) },
}));

const base: ReviewReadiness = {
  submittal_document_id: "sub-1", pages_total: null, pages_read: null, unread_pages: [],
  unread_page_reasons: {}, standards_cited: 0, standards_held: [], standards_missing: [],
  last_run_id: null, nothing_changed: false, changes: [],
};

describe("ReadinessStrip and the page ledger", () => {
  it("says the ledger is not built yet instead of counting 0 pages", () => {
    render(<ReadinessStrip readiness={{ ...base, ledger_state: "missing",
      ledger_note: "the page ledger for this document is not built yet; reading the sheet into fields or running a review builds it" }}
      onReread={async () => {}} />);
    expect(screen.getByTestId("ledger-note")).toHaveTextContent("Pages read: not counted yet - the page ledger for this document is not built yet");
    expect(screen.queryByText(/Pages read: 0/)).toBeNull();
  });

  it("counts the pages when the ledger is current, and says nothing about the ledger", () => {
    render(<ReadinessStrip readiness={{ ...base, pages_total: 3, pages_read: 2, unread_pages: [3],
      unread_page_reasons: { "3": "no text on this page" }, ledger_state: "current", ledger_note: null }}
      onReread={async () => {}} />);
    expect(screen.getByText(/Pages read: 2 of 3/)).toBeInTheDocument();
    expect(screen.queryByTestId("ledger-note")).toBeNull();
  });

  it("names pages read with no checklist field apart, so the pages add up (order 165)", () => {
    render(<ReadinessStrip readiness={{ ...base, pages_total: 11, pages_read: 8, pages_read_no_field: [1, 2, 3],
      unread_pages: [], ledger_state: "current", ledger_note: null }}
      onReread={async () => {}} />);
    expect(screen.getByText(/Pages read: 8 of 11; pages 1-3 read, no checklist field found/)).toBeInTheDocument();
    expect(screen.queryByText(/not read:/)).toBeNull();
  });
});
