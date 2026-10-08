/**
 * The Standards Library screen.
 *
 * What these assert is what the screen REFUSES to say, because that is where
 * this product's value is:
 *
 *  - a standard with nothing extracted says so, and never "0 requirements",
 *    which reads as "this standard requires nothing";
 *  - a requirement whose clause could not be identified says "clause not
 *    identified" and never a guessed number;
 *  - a superseded standard is labelled and still openable;
 *  - an extracted-but-unconfirmed requirement is labelled a guess.
 *
 * Mutations: M35-M38 in `scripts/mutation_check.py`; the phase-3B
 * structured reading, M1620-M1639 in `scripts/mutations/standards_structured.py`.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { StandardsView } from "./StandardsView";
import type { StandardRequirement, StandardSummary } from "../types/api";

const base: StandardSummary = {
  id: "doc_std", filename: "SAES-A-105.pdf", status: "ready", page_count: 20,
  uploaded_at: "2026-09-18T00:00:00Z", title: "Coating systems",
  document_number: "SAES-A-105", revision: "2021", effective_date: "2021-03-01",
  discipline: "Mechanical", superseded_by: null, superseded: false,
  requirement_count: 0, awaiting_verification: 0,
};

const requirement: StandardRequirement = {
  id: "r1", standard_document_id: "doc_std", clause: "5.3.3", page: 9,
  chunk_id: "c1", requirement_text: "The coating shall be applied in three coats.",
  source_text: "The coating shall be applied in three coats.", category: null,
  extraction_method: "extracted", confidence: 0.9, confirmed_by: null,
  confirmed_at: null, needs_verification: false, citation_resolves: true,
  created_at: "2026-09-18T00:00:00Z", updated_at: "2026-09-18T00:00:00Z",
  // Phase 3B: every structured field null, which is what a statement with no
  // recognised limit - and every pre-3B row - looks like.
  requirement_type: null, field: null, operator: null, value: null, unit: null,
  raw_value: null, raw_unit: null, condition: null, exceptions: [],
  discipline: null, table_row: null,
};

function mockApi(opts: {
  standards?: StandardSummary[];
  requirements?: StandardRequirement[];
  revisions?: StandardSummary[];
  onPost?: (url: string, body: unknown) => void;
  /** Answer this list with a server error instead of a body. */
  failing?: "requirements" | "revisions";
} = {}) {
  const json = (body: unknown) =>
    new Response(JSON.stringify(body), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const href = String(url);
    if (init?.method === "POST") {
      opts.onPost?.(href, init.body ? JSON.parse(String(init.body)) : null);
      if (href.includes("/extract")) {
        return json({ document_id: "doc_std", chunks_read: 3, requirements: 1,
                      awaiting_verification: 0 });
      }
      return json({ superseded_by: null });
    }
    if (href.includes("/standards/missing")) return json([]);
    if (opts.failing && href.includes(`/${opts.failing}`)) {
      return new Response(JSON.stringify({ error: { code: "internal_error", message: "the list broke" } }), {
        status: 500, headers: { "Content-Type": "application/json" },
      });
    }
    if (href.includes("/requirements")) return json(opts.requirements ?? []);
    if (href.includes("/revisions")) return json(opts.revisions ?? [base]);
    if (href.includes("/clauses")) return json([]);
    return json(opts.standards ?? [base]);
  }));
}

beforeEach(() => { vi.restoreAllMocks(); });

describe("the library list", () => {
  it("says no requirements have been extracted, not '0 requirements'", async () => {
    mockApi({ standards: [{ ...base, requirement_count: 0 }] });
    render(<StandardsView />);
    expect(await screen.findByText(/no requirements extracted yet/i)).toBeTruthy();
    // "0 requirements" would read as "this standard requires nothing".
    expect(screen.queryByText(/^0 requirements/)).toBeNull();
  });

  it("counts requirements when there are some", async () => {
    mockApi({ standards: [{ ...base, requirement_count: 12, awaiting_verification: 3 }] });
    render(<StandardsView />);
    expect(await screen.findByText(/12 requirements/)).toBeTruthy();
    expect(screen.getByText(/3 awaiting verification/)).toBeTruthy();
  });

  it("labels a superseded standard and still lets it be opened", async () => {
    mockApi({ standards: [{ ...base, superseded: true, superseded_by: "doc_new" }] });
    render(<StandardsView />);
    expect(await screen.findByText("Superseded")).toBeTruthy();
    // Still openable: readable and citable is a different question from
    // selectable.
    fireEvent.click(screen.getByRole("button", { name: /SAES-A-105/ }));
    expect(await screen.findByRole("tablist", { name: "Standard detail" })).toBeTruthy();
  });

  it("shows an active standard as active", async () => {
    mockApi();
    render(<StandardsView />);
    expect(await screen.findByText("Active")).toBeTruthy();
  });

  it("renders nothing for a field that was never recorded", async () => {
    mockApi({ standards: [{ ...base, discipline: null, revision: null,
                            effective_date: null, title: null }] });
    render(<StandardsView />);
    await screen.findByText(/no requirements extracted yet/i);
    expect(screen.queryByText("Unknown")).toBeNull();
    expect(screen.queryByText(/^Rev /)).toBeNull();
  });
});

describe("the requirements tab", () => {
  it("says a clause could not be identified rather than guessing one", async () => {
    mockApi({
      requirements: [{ ...requirement, clause: null, confidence: 0.6,
                       needs_verification: true }],
    });
    render(<StandardsView />);
    fireEvent.click(await screen.findByRole("button", { name: /SAES-A-105/ }));
    expect(await screen.findByText("Clause not identified")).toBeTruthy();
    expect(screen.getByText("Awaiting verification")).toBeTruthy();
  });

  it("labels an extracted requirement as not yet confirmed", async () => {
    mockApi({ requirements: [requirement] });
    render(<StandardsView />);
    fireEvent.click(await screen.findByRole("button", { name: /SAES-A-105/ }));
    expect(await screen.findByText("Extracted, not confirmed")).toBeTruthy();
    expect(screen.getByText("5.3.3")).toBeTruthy();
    expect(screen.getByText(/page 9/)).toBeTruthy();
  });

  it("warns when a citation no longer resolves", async () => {
    mockApi({ requirements: [{ ...requirement, citation_resolves: false }] });
    render(<StandardsView />);
    fireEvent.click(await screen.findByRole("button", { name: /SAES-A-105/ }));
    expect(await screen.findByText(/citation no longer resolves/i)).toBeTruthy();
  });

  it("says the standard has not been read, not that it has no requirements", async () => {
    mockApi({ requirements: [] });
    render(<StandardsView />);
    fireEvent.click(await screen.findByRole("button", { name: /SAES-A-105/ }));
    expect(
      await screen.findByText(/no requirements have been extracted from this standard yet/i),
    ).toBeTruthy();
  });

  it("offers extraction only to an administrator", async () => {
    mockApi({ requirements: [] });
    const { unmount } = render(<StandardsView isAdmin={false} />);
    fireEvent.click(await screen.findByRole("button", { name: /SAES-A-105/ }));
    await screen.findByText(/no requirements have been extracted/i);
    expect(screen.queryByRole("button", { name: /extract requirements/i })).toBeNull();
    unmount();

    mockApi({ requirements: [] });
    render(<StandardsView isAdmin />);
    fireEvent.click(await screen.findByRole("button", { name: /SAES-A-105/ }));
    expect(await screen.findByRole("button", { name: /extract requirements/i })).toBeTruthy();
  });
});

describe("the revision history tab", () => {
  it("lists the other revisions of the same standard number", async () => {
    mockApi({
      revisions: [
        { ...base, id: "doc_old", revision: "2019", superseded: true,
          superseded_by: "doc_std" },
        base,
      ],
    });
    render(<StandardsView />);
    fireEvent.click(await screen.findByRole("button", { name: /SAES-A-105/ }));
    fireEvent.click(screen.getByRole("tab", { name: "Revision History" }));
    expect(await screen.findByText("2019")).toBeTruthy();
    expect(screen.getByText("superseded")).toBeTruthy();
  });

  it("sends the supersede decision to the server", async () => {
    const posts: Array<{ url: string; body: unknown }> = [];
    mockApi({
      revisions: [{ ...base, id: "doc_new", revision: "2024" }, base],
      onPost: (url, body) => posts.push({ url, body }),
    });
    render(<StandardsView isAdmin />);
    fireEvent.click(await screen.findByRole("button", { name: /SAES-A-105/ }));
    fireEvent.click(screen.getByRole("tab", { name: "Revision History" }));
    const select = await screen.findByLabelText("Superseded by");
    fireEvent.change(select, { target: { value: "doc_new" } });
    await waitFor(() => expect(posts.length).toBe(1));
    expect(posts[0].url).toContain("/standards/doc_std/supersede");
    expect(posts[0].body).toEqual({ superseded_by: "doc_new" });
  });

  it("does not offer the supersede control to a non-admin", async () => {
    mockApi({ revisions: [base] });
    render(<StandardsView isAdmin={false} />);
    fireEvent.click(await screen.findByRole("button", { name: /SAES-A-105/ }));
    fireEvent.click(screen.getByRole("tab", { name: "Revision History" }));

    // WAIT FOR THE TAB TO HAVE LOADED BEFORE ASSERTING AN ABSENCE.
    //
    // The first version of this test went straight to
    // `waitFor(() => expect(queryByLabelText(...)).toBeNull())`, which passes
    // on its FIRST tick - and on that tick the tab is still a spinner, so
    // nothing is on screen to find. It passed with the permission check
    // deleted (mutation M38 reported NOT DETECTED), because it was asserting
    // that a control had not rendered YET rather than that it never would.
    //
    // A positive assertion first is what makes the negative one mean
    // something: the revision list is on screen, so the form would be too.
    expect(await screen.findByText("2021")).toBeTruthy();
    expect(screen.queryByLabelText("Superseded by")).toBeNull();
  });
});

describe("the tab strip", () => {
  it("has no Applicability tab - that is phase 3B and is not half-built", async () => {
    mockApi();
    render(<StandardsView />);
    fireEvent.click(await screen.findByRole("button", { name: /SAES-A-105/ }));
    const tabs = (await screen.findAllByRole("tab")).map((t) => t.textContent);
    expect(tabs).toEqual([
      "Original Document", "Requirements", "Revision History", "Processing Details",
    ]);
  });
});

describe("audit 2026-09-30: a tab whose list failed says so, to everyone", () => {
  it("shows a requirements load failure to a non-admin instead of spinning", async () => {
    mockApi({ failing: "requirements" });
    render(<StandardsView isAdmin={false} />);
    fireEvent.click(await screen.findByRole("button", { name: /SAES-A-105/ }));
    expect(await screen.findByText(/The requirements of this standard could not be loaded/))
      .toBeTruthy();
    expect(screen.queryByText(/no requirements have been extracted/i)).toBeNull();
  });

  it("shows a revisions load failure instead of spinning", async () => {
    mockApi({ failing: "revisions" });
    render(<StandardsView isAdmin={false} />);
    fireEvent.click(await screen.findByRole("button", { name: /SAES-A-105/ }));
    fireEvent.click(screen.getByRole("tab", { name: "Revision History" }));
    expect(await screen.findByText(/The revisions of this standard could not be loaded/))
      .toBeTruthy();
    expect(screen.queryByText(/No other revisions/)).toBeNull();
  });
});

describe("the structured reading of a requirement (phase 3B)", () => {
  const limitRow: StandardRequirement = {
    ...requirement, id: "r_limit", clause: "6.1.2",
    requirement_text: "For pipes larger than 2 inch, the wall thickness shall be at least 3 mm, except for pressure relief valves, which shall not exceed 115 dB(A).",
    requirement_type: "numeric_limit", operator: ">=", value: 3, unit: "mm",
    raw_value: "3", raw_unit: "mm", condition: "pipes larger than 2 inch",
    exceptions: [{ applies_to: "pressure relief valves", operator: "<=",
                   raw_value: "115", raw_unit: "dB(A)", value: 115, unit: "dB(A)" }],
  };

  async function openRequirements(rows: StandardRequirement[]) {
    mockApi({ requirements: rows });
    render(<StandardsView />);
    fireEvent.click(await screen.findByRole("button", { name: /SAES-A-105/ }));
    await screen.findByText(rows[0].requirement_text);
  }

  it("shows the limit, condition and exception beside the quoted clause", async () => {
    await openRequirements([limitRow]);
    const reading = screen.getByRole("region", { name: /machine-extracted from the quoted clause/i });
    // The quoted clause stays the primary content, outside the reading.
    expect(reading.textContent).not.toContain(limitRow.requirement_text);
    const pairs = [...reading.querySelectorAll("dt")].map((dt) =>
      [dt.textContent, dt.nextElementSibling?.textContent]);
    expect(pairs).toContainEqual(["Limit", "≥ 3 mm"]);
    expect(pairs).toContainEqual(["Applies to", "pipes larger than 2 inch"]);
    expect(pairs).toContainEqual(["Except", "pressure relief valves (≤ 115 dB(A))"]);
  });

  it("labels the reading a machine guess until an engineer confirms the row", async () => {
    await openRequirements([limitRow]);
    expect(screen.getByRole("region", {
      name: "Machine-extracted from the quoted clause - not confirmed by an engineer",
    })).toBeTruthy();
    cleanup();
    await openRequirements([{ ...limitRow, confirmed_by: "u_eng", extraction_method: "human",
                              confirmed_at: "2026-09-20T00:00:00Z" }]);
    expect(screen.getByRole("region", { name: /confirmed by an engineer$/ })).toBeTruthy();
    expect(screen.queryByText(/not confirmed by an engineer/)).toBeNull();
  });

  it("renders nothing for a row whose structured fields are all null", async () => {
    await openRequirements([requirement]);
    expect(screen.queryByRole("region", { name: /machine-extracted/i })).toBeNull();
    expect(screen.queryByText("Limit")).toBeNull();
    expect(screen.queryByText("Applies to")).toBeNull();
    expect(screen.queryByText("Except")).toBeNull();
    // Null is never rendered as a limit of zero.
    const item = screen.getByText(requirement.requirement_text).closest("li");
    expect(item?.textContent).not.toMatch(/\b0\b/);
  });

  it("omits each null field on its own and never shows a bare operator", async () => {
    await openRequirements([{ ...limitRow, condition: null, exceptions: [],
                              raw_value: null, value: null }]);
    // Only the type remains, and a type alone does not earn a box.
    expect(screen.queryByRole("region", { name: /machine-extracted/i })).toBeNull();
    expect(screen.queryByText("≥")).toBeNull();
  });

  it("falls back to the normalised value when the raw one was not kept", async () => {
    await openRequirements([{ ...limitRow, raw_value: null, raw_unit: null,
                              operator: "<=", value: 600, unit: "psi" }]);
    const reading = screen.getByRole("region", { name: /machine-extracted/i });
    expect(reading.textContent).toContain("≤ 600 psi");
  });

  it("quotes the value as the document wrote it, not the normalised one", async () => {
    await openRequirements([{ ...limitRow, raw_value: "1/2", raw_unit: "in",
                              value: 12.7, unit: "mm" }]);
    const reading = screen.getByRole("region", { name: /machine-extracted/i });
    expect(reading.textContent).toContain("≥ 1/2 in");
    expect(reading.textContent).not.toContain("12.7");
  });

  it("calls a table value's condition a ROW LABEL, never 'applies to'", async () => {
    await openRequirements([{
      ...requirement, id: "r_table", requirement_text: "Arsenic - Max (mg/kg): 20",
      requirement_type: "table_value", field: "Max", operator: null,
      raw_value: "20", raw_unit: "mg/kg", value: 20, unit: "mg/kg",
      condition: "Arsenic", table_row: 3,
    }]);
    const reading = screen.getByRole("region", { name: /machine-extracted/i });
    const pairs = [...reading.querySelectorAll("dt")].map((dt) =>
      [dt.textContent, dt.nextElementSibling?.textContent]);
    expect(pairs).toContainEqual(["Table row", "Arsenic"]);
    expect(pairs).toContainEqual(["Table column", "Max"]);
    expect(pairs).toContainEqual(["Cell value", "20 mg/kg"]);
    expect(screen.queryByText("Applies to")).toBeNull();
    expect(screen.queryByText("Limit")).toBeNull();
  });

  it("drops a malformed exception entry instead of rendering an empty line", async () => {
    await openRequirements([{ ...limitRow,
      exceptions: [{ applies_to: "" }, { applies_to: "flare tips" }] }]);
    const reading = screen.getByRole("region", { name: /machine-extracted/i });
    const items = [...reading.querySelectorAll("li")].map((li) => li.textContent);
    expect(items).toEqual(["flare tips"]);
  });
});
