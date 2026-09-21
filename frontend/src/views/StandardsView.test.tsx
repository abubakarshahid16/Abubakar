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
 * Mutations: M35-M38 in `scripts/mutation_check.py`.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

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
};

function mockApi(opts: {
  standards?: StandardSummary[];
  requirements?: StandardRequirement[];
  revisions?: StandardSummary[];
  onPost?: (url: string, body: unknown) => void;
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
