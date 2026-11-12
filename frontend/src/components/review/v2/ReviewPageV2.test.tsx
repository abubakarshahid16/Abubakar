/**
 * The redesigned review page: every element of SPEC.md (owner, 12 Nov 2026). The backend routes are mocked; what is checked is what a
 * user sees and what the page asks the server to do.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PointsListing, ReviewPlan, ReviewPoint } from "../../../api/reviewPoints";
import { hasBannedWord } from "../agent/plainWords";
import { ReviewPageV2 } from "./ReviewPageV2";
import { costWords, engineWords, signWaits, tileLine, wontRunWords } from "./words";

const api = {
  list: vi.fn(), plan: vi.fn(), decide: vi.fn(), keepAll: vi.fn(), add: vi.fn(), start: vi.fn(), recordYes: vi.fn(),
  ofDocument: vi.fn(), kinds: vi.fn(), confirmKind: vi.fn(), decideCode: vi.fn(), downloadCrs: vi.fn(), downloadAgentCrs: vi.fn(),
};
vi.mock("../../../api/reviewPoints", async (orig) => ({
  ...(await orig<typeof import("../../../api/reviewPoints")>()),
  reviewPoints: {
    list: (...a: unknown[]) => api.list(...a), plan: (...a: unknown[]) => api.plan(...a), decide: (...a: unknown[]) => api.decide(...a),
    keepAll: (...a: unknown[]) => api.keepAll(...a), add: (...a: unknown[]) => api.add(...a), start: (...a: unknown[]) => api.start(...a),
    recordYes: (...a: unknown[]) => api.recordYes(...a),
  },
}));
vi.mock("../../../api/documents", () => ({
  classification: {
    ofDocument: (...a: unknown[]) => api.ofDocument(...a), kinds: (...a: unknown[]) => api.kinds(...a),
    confirmKind: (...a: unknown[]) => api.confirmKind(...a),
  },
}));
vi.mock("../../../api/client", () => ({ reviews: { decideCode: (...a: unknown[]) => api.decideCode(...a) } }));
vi.mock("../downloadCrs", () => ({ downloadCrs: (...a: unknown[]) => api.downloadCrs(...a) }));
vi.mock("../agent/downloadAgentCrs", () => ({ downloadAgentCrs: (...a: unknown[]) => api.downloadAgentCrs(...a) }));
vi.mock("../../PageImageViewer", () => ({
  PageImageViewer: ({ initialPage }: { initialPage?: number }) => <div data-testid="viewer">viewer at page {initialPage}</div>,
}));

const ok = <T,>(data: T) => ({ ok: true, data });

function point(over: Partial<ReviewPoint>): ReviewPoint {
  return {
    id: "ai:r:1", source: "ai_review", source_words: "AI review", engine: "AI reviewer on Claude", rank: 1, tile: "not_met",
    firm: "proven by code", other_kind: null, name: "Design pressure", page: 4, rule_book: "API 610", clause: "6.2",
    action: "Contractor to revise the design pressure to meet API 610 clause 6.2 and resubmit the paper.",
    paper_quote: "2.2 bar (ga)", clause_quote: "The design pressure shall be 6,900 kPa.",
    paper_quote_note: "Checked by code: found on the page.", clause_quote_note: "Checked by code: found in the clause.",
    route_note: null, view_page: { document_id: "doc1", page: 4, image_url: "/api/documents/doc1/pages/4/image" },
    group_key: null, added_by: null, n_alike: 1, pill: "Not met · proven by code", decision: { state: null, words: "Not decided" }, ...over,
  };
}

const alike = (i: number) => point({
  id: `ai:r:q${i}`, rank: 4, tile: "questions", firm: null, name: `Nameplate ${i}`, pill: "Question · 4 alike", group_key: "g1", n_alike: 4,
  paper_quote: null, clause_quote: null, paper_quote_note: "No verified quote from the paper for this point.",
  clause_quote_note: "No verified quote from the rule book clause for this point.", action: "Contractor to state the value.", page: 2 + i,
});

function listing(over: Partial<PointsListing> = {}): PointsListing {
  const points = [
    point({}),
    point({ id: "ai:r:2", rank: 2, tile: "not_met", firm: "two readers agree", name: "Material", pill: "Not met · two readers agree",
      route_note: "Two readers reached this verdict independently.", paper_quote: null, paper_quote_note: "No verified quote from the paper for this point." }),
    point({ id: "ai:r:3", rank: 3, tile: "not_met", firm: "one reader", name: "Weight", pill: "Not met · one reader", rule_book: "Other Book", clause: "3" }),
    alike(1), alike(2), alike(3), alike(4),
    point({ id: "ai:r:9", rank: 7, tile: "met", firm: "proven by code", name: "Tag", pill: "Met · proven by code", decision: { state: "keep", words: "Kept", by: "Sana" } }),
    point({ id: "add:1", source: "added", source_words: "Added by an engineer", engine: null, rank: 4, tile: "questions", name: "Check the P&ID",
      pill: "Added by Sana", added_by: "Sana", rule_book: null, clause: null, decision: { state: "keep", words: "Added" } }),
  ];
  return {
    paper_document_id: "doc1", runs: { rule_check: "rc1", ai_review: "ai1" }, points,
    counts: {
      tiles: {
        not_met: { label: "Not met", total: 3, two_readers: 1, one_reader: 1, proven_by_code: 1 },
        questions: { label: "Questions", total: 5, groups: 2 },
        met: { label: "Met", total: 1, two_readers: 0, one_reader: 0, proven_by_code: 1 },
        does_not_apply: { label: "Does not apply", total: 0, proven_by_code: null },
      },
      total: 9, rule_books: [{ name: "API 610", points: 6 }, { name: "Other Book", points: 1 }], other_rule_books_points: 2,
      other_rule_books_note: "points on rule books you may not read: counted, not named",
      not_held: { names: ["Book A", "Book B", "Book C"], more: 2, total: 5, note: "Not checked, rule book not held" },
      decided: 2, decided_of: 9,
    },
    proposed_code: { code: "Approved with Comments", reason: "2 kept comments; none is proven by code to fail a 'shall' rule.", line: "So far: Approved with Comments, 7 points still to decide", so_far: true, undecided: 7, rule: "r", proposed_by: "the system; the engineer decides" },
    final_code: null, code_run_id: "rc1", decided: 2, of: 9, removed: [],
    contractor_copy: { kind: "datasheet", words: "The contractor file holds only what code proved, or your own words. It never carries an AI wording." }, ...over,
  };
}

const plan = (over: Partial<ReviewPlan> = {}): ReviewPlan => ({
  choice: "automatic", parts: [{ name: "rule_check", engine: "claude", why: "x" }, { name: "ai_review", engine: "claude", why: "y" }],
  text_leaves: true, refused: null, refused_code: null, needs_yes: false, unscored: false, wont_run: [], kind: "datasheet",
  documents: { paper: true, rule_books: ["API 610", "Other Book", "Third", "Fourth"], rule_books_note: null },
  cost: { at_most_usd: 30, by_part_at_most_usd: { rule_check: 15, ai_review: 15 }, basis: "b", last_review_usd: 0.5, last_review_note: "n", exact: false },
  notes: [], sentence: "s", contract_yes: null, ...over,
});

const RUN = { review_run_id: "rc1", submittal_document_id: "doc1", submittal_filename: "Pump datasheet.pdf" } as never;
const DOC = { id: "doc1", filename: "Pump datasheet.pdf", page_count: 12 } as never;

function mount(over: Partial<React.ComponentProps<typeof ReviewPageV2>> = {}) {
  const props = {
    run: RUN, submittal: DOC, isAdmin: true, onBack: vi.fn(), onOpenRun: vi.fn(), sheetTab: <p>the sheet</p>, howTab: <p>how it was reviewed body</p>,
    onSign: vi.fn(), signBlockers: [] as string[], signed: false, onCodeRecorded: vi.fn(), ...over,
  };
  return { ...render(<ReviewPageV2 {...props} />), props };
}

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  api.list.mockResolvedValue(ok(listing()));
  api.plan.mockResolvedValue(ok(plan()));
  api.ofDocument.mockResolvedValue(ok({ document_kind: "datasheet", document_kind_state: "suggested", equipment_type: "pressure_relief_valve" }));
  api.kinds.mockResolvedValue(ok({ kinds: [{ id: "datasheet", label: "Datasheet" }] }));
  api.downloadCrs.mockResolvedValue(null);
  api.downloadAgentCrs.mockResolvedValue(null);
});

const loaded = async () => { await screen.findByTestId("v2-points"); };

describe("1 the header", () => {
  it("names the paper and the kind line with who decided, and a Change for the kind", async () => {
    mount(); await loaded();
    expect(screen.getByRole("heading", { name: "Pump datasheet.pdf" })).toBeInTheDocument();
    const line = await screen.findByTestId("v2-kind-line");
    await waitFor(() => expect(line).toHaveTextContent("pressure relief valve"));
    expect(line).toHaveTextContent("12 pages");
    // ONE line says the guess once: the chip says it, the line does not repeat it.
    expect(screen.getByTestId("kind-chip")).toHaveTextContent("Datasheet?");
    expect(line.textContent ?? "").not.toMatch(/kind decided by/);
    expect((line.textContent ?? "").match(/guess/gi)).toHaveLength(1);
  });
  it("a confirmed kind says who decided it", async () => {
    api.ofDocument.mockResolvedValue(ok({ document_kind: "datasheet", document_kind_state: "confirmed", equipment_type: "pressure_relief_valve" }));
    mount(); await loaded();
    await waitFor(() => expect(screen.getByTestId("v2-kind-line")).toHaveTextContent("kind decided by an engineer"));
  });
  it("has ONE engine choice with Automatic preselected and ONE Review button; the old two buttons are not here", async () => {
    mount(); await loaded();
    const group = screen.getByRole("radiogroup");
    const radios = within(group).getAllByRole("radio");
    expect(radios.map((r) => r.textContent)).toEqual(["Automatic", "Claude", "Local only"]);
    expect(radios[0]).toHaveAttribute("aria-checked", "true");
    expect(screen.getAllByRole("button", { name: "Review" })).toHaveLength(1);
    expect(screen.queryByText(/Start AI review|Review again/)).toBeNull();
  });
  it("starts with the chosen engine and opens the new review", async () => {
    api.start.mockResolvedValue(ok({ review_run_id: "run-new" }));
    const { props } = mount(); await loaded();
    await screen.findByTestId("v2-engine-line");
    fireEvent.click(screen.getByRole("radio", { name: "Local only" }));
    await waitFor(() => expect(api.plan).toHaveBeenLastCalledWith("doc1", "local"));
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith("doc1", "local"));
    await waitFor(() => expect(props.onOpenRun).toHaveBeenCalledWith("run-new"));
  });
  it("a non-admin is told who can start a review", async () => {
    mount({ isAdmin: false }); await loaded();
    expect(screen.queryByRole("button", { name: "Review" })).toBeNull();
    expect(screen.getByText("Only an administrator can start a review.")).toBeInTheDocument();
  });
});

describe("2 the engine line", () => {
  it("says the engine, what leaves, and the cost as about x, limit y", async () => {
    mount(); await loaded();
    const line = await screen.findByTestId("v2-engine-line");
    expect(line).toHaveTextContent("Engine: Claude. Text of this paper and of 4 rule books will leave this computer.");
    expect(line).toHaveTextContent("Cost: about USD 0.50, limit USD 30");
  });
  it("shows the limit alone when no earlier review has a real cost", () => {
    expect(costWords(plan({ cost: { ...plan().cost, last_review_usd: null } }))).toBe("Cost: limit USD 30");
    expect(costWords(plan({ text_leaves: false, cost: { ...plan().cost, at_most_usd: null } }))).toBeNull();
  });
  it("Local only says the AI review will not run and nothing leaves", async () => {
    api.plan.mockResolvedValue(ok(plan({
      choice: "local", text_leaves: false, cost: { ...plan().cost, at_most_usd: null },
      parts: [{ name: "rule_check", engine: "local", why: "z" }, { name: "ai_review", engine: "not_run", why: "The AI review needs Claude and will not run; the rule check runs on this computer" }],
    })));
    mount(); await loaded();
    const line = await screen.findByTestId("v2-engine-line");
    expect(line).toHaveTextContent("Engine: this computer. No text leaves this computer.");
    expect(line).toHaveTextContent("The AI review will not run: the rule check runs on this computer.");
    expect(line).not.toHaveTextContent("Cost:");
  });
  it("an engine the install does not allow is a plain sentence and no Review button press", async () => {
    api.plan.mockResolvedValue(ok(plan({ refused: "Claude cannot be used for this paper: the connection to Claude is closed on this install (flags or key)", text_leaves: false })));
    mount(); await loaded();
    expect(await screen.findByText(/Claude cannot be used for this paper/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review" })).toBeDisabled();
  });
  it("a contract on Claude shows the owner's yes and, for an admin, the button that records it", async () => {
    api.plan.mockResolvedValueOnce(ok(plan({ needs_yes: true }))).mockResolvedValue(ok(plan({ needs_yes: false })));
    api.recordYes.mockResolvedValue(ok({}));
    mount(); await loaded();
    expect(await screen.findByTestId("v2-needs-yes")).toHaveTextContent("needs the owner's yes for this upload");
    fireEvent.click(screen.getByRole("button", { name: "Record the owner's yes" }));
    await waitFor(() => expect(api.recordYes).toHaveBeenCalledWith("doc1"));
    await waitFor(() => expect(screen.queryByTestId("v2-needs-yes")).toBeNull());
  });
  it("the words come from one place", () => {
    expect(engineWords(plan({ text_leaves: true }))).toContain("will leave this computer");
    expect(wontRunWords(plan({ wont_run: [{ part: "contract checklist", why: "empty; an engineer must write it" }] }))).toEqual(["contract checklist: empty; an engineer must write it."]);
  });
});

describe("3 the review code box", () => {
  it("shows the proposed code, ONE line of reason and x of N decided", async () => {
    mount(); await loaded();
    expect(screen.getByTestId("v2-code-line")).toHaveTextContent("So far: Approved with Comments, 7 points still to decide");
    expect(screen.getByTestId("v2-code-reason")).toHaveTextContent("2 kept comments");
    expect(screen.getByText("proposed by the system; you decide")).toBeInTheDocument();
    expect(screen.getByTestId("v2-decided")).toHaveTextContent("2 of 9 decided");
  });
  it("records the final code, asking why when it is not the proposed one", async () => {
    api.decideCode.mockResolvedValue(ok({}));
    const { props } = mount(); await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Record the code" }));
    fireEvent.change(screen.getByLabelText("Final code"), { target: { value: "Approved" } });
    fireEvent.click(screen.getByRole("button", { name: "Record final code" }));
    expect(await screen.findByText(/A reason is needed/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Why it differs"), { target: { value: "checked by hand" } });
    fireEvent.click(screen.getByRole("button", { name: "Record final code" }));
    await waitFor(() => expect(api.decideCode).toHaveBeenCalledWith("rc1", "Approved", "checked by hand"));
    await waitFor(() => expect(props.onCodeRecorded).toHaveBeenCalled());
  });
});

describe("4 the four tiles", () => {
  it("each is a big number with one small line; a count the review cannot have is not shown", async () => {
    mount(); await loaded();
    expect(screen.getByTestId("v2-tile-not_met")).toHaveTextContent("3");
    expect(screen.getByTestId("v2-tile-not_met")).toHaveTextContent("1 two readers · 1 one reader · 1 proven by code");
    expect(screen.getByTestId("v2-tile-questions")).toHaveTextContent("in 2 groups");
    expect(screen.getByTestId("v2-tile-does_not_apply")).toHaveTextContent("0");
    expect(tileLine("does_not_apply", { label: "x", total: 0, proven_by_code: null })).toBe("");
    expect(tileLine("not_met", { label: "x", total: 2, two_readers: null, one_reader: 2, proven_by_code: 0 })).toBe("2 one reader");
  });
  it("a tile filters the list, is outlined, and the page says what it shows", async () => {
    mount(); await loaded();
    expect(screen.getAllByTestId("v2-point").length + screen.getAllByTestId("v2-group").length).toBeGreaterThan(3);
    fireEvent.click(screen.getByTestId("v2-tile-met"));
    expect(screen.getByTestId("v2-tile-met")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Showing: Met\. Click a tile to filter the list\./)).toBeInTheDocument();
    expect(screen.getAllByTestId("v2-point")).toHaveLength(1);
    fireEvent.click(screen.getByTestId("v2-tile-met"));
    expect(screen.getByText(/Showing: every point/)).toBeInTheDocument();
  });
  it("one line says how firm the result is", async () => {
    mount(); await loaded();
    expect(screen.getByTestId("v2-firm")).toHaveTextContent("2 proven by code, 1 agreed by two readers, 1 one reader's view. A person decides each point.");
  });
});

describe("5 and 6 the rule book chips and the rule books not held", () => {
  it("shows All rule books and each rule book by its name with its count, and filters", async () => {
    mount(); await loaded();
    const chips = screen.getByTestId("v2-books");
    expect(within(chips).getByRole("button", { name: "All rule books" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(chips).getByRole("button", { name: "Other Book (1)" }));
    expect(screen.getAllByTestId("v2-point")).toHaveLength(1);
    expect(screen.getByText("2 on rule books you may not read")).toBeInTheDocument();
  });
  it("names the first three rule books not held and counts the rest", async () => {
    mount(); await loaded();
    expect(screen.getByTestId("v2-not-held")).toHaveTextContent("Not checked, rule book not held: Book A, Book B, Book C and 2 more. See all");
  });
  it("shows nothing when none is missing", async () => {
    const l = listing(); l.counts.not_held = { names: [], more: 0, total: 0, note: null };
    api.list.mockResolvedValue(ok(l));
    mount(); await loaded();
    expect(screen.queryByTestId("v2-not-held")).toBeNull();
  });
});

describe("7 the three tabs", () => {
  it("has Points (N), CRS sheet and How it was reviewed, and the old screens live under the last two", async () => {
    mount(); await loaded();
    const tabs = screen.getAllByRole("tab").map((t) => t.textContent);
    expect(tabs).toEqual(["Points (9)", "CRS sheet", "How it was reviewed"]);
    fireEvent.click(screen.getByRole("tab", { name: "CRS sheet" }));
    expect(screen.getByTestId("v2-sheet-tab")).toHaveTextContent("the sheet");
    fireEvent.click(screen.getByRole("tab", { name: "How it was reviewed" }));
    expect(screen.getByTestId("v2-how-tab")).toHaveTextContent("how it was reviewed body");
  });
  it("See all opens How it was reviewed", async () => {
    mount(); await loaded();
    fireEvent.click(screen.getByRole("button", { name: "See all" }));
    expect(screen.getByRole("tab", { name: "How it was reviewed" })).toHaveAttribute("aria-selected", "true");
  });
});

describe("8 the list of points", () => {
  it("is ONE list, worst first, each row with a pill, a plain name and where it is", async () => {
    mount(); await loaded();
    const pills = screen.getAllByTestId("v2-pill").map((p) => p.textContent);
    expect(pills.slice(0, 3)).toEqual(["Not met · proven by code", "Not met · two readers agree", "Not met · one reader"]);
    const first = screen.getAllByTestId("v2-point")[0];
    expect(first).toHaveTextContent("Design pressure");
    expect(first).toHaveTextContent("page 4 · API 610, clause 6.2");
  });
  it("Keep decides the point", async () => {
    api.decide.mockResolvedValue(ok(listing()));
    mount(); await loaded();
    const row = screen.getAllByTestId("v2-point")[0];
    fireEvent.click(within(row).getByRole("button", { name: "Keep" }));
    await waitFor(() => expect(api.decide).toHaveBeenCalledWith("doc1", { point_id: "ai:r:1", state: "keep" }));
  });
  it("Edit sends the engineer's own wording", async () => {
    api.decide.mockResolvedValue(ok(listing()));
    mount(); await loaded();
    const row = screen.getAllByTestId("v2-point")[0];
    fireEvent.click(within(row).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(row).getByLabelText("Your wording"), { target: { value: "My own words." } });
    fireEvent.click(within(row).getByRole("button", { name: "Save my wording" }));
    await waitFor(() => expect(api.decide).toHaveBeenCalledWith("doc1", { point_id: "ai:r:1", state: "edit", text: "My own words." }));
  });
  it("Remove needs a one-line reason and says it stays in the record", async () => {
    api.decide.mockResolvedValue(ok(listing()));
    mount(); await loaded();
    const row = screen.getAllByTestId("v2-point")[0];
    fireEvent.click(within(row).getByRole("button", { name: "Remove" }));
    expect(within(row).getByText(/stays in the record with this reason/)).toBeInTheDocument();
    const go = within(row).getByRole("button", { name: "Remove it" });
    expect(go).toBeDisabled();
    fireEvent.change(within(row).getByLabelText("Why it is removed"), { target: { value: "the paper states it on page 9" } });
    expect(go).toBeEnabled();
    fireEvent.click(go);
    await waitFor(() => expect(api.decide).toHaveBeenCalledWith("doc1", { point_id: "ai:r:1", state: "remove", reason: "the paper states it on page 9" }));
  });
  it("a decided point shows its state and who decided; Change brings the buttons back", async () => {
    mount(); await loaded();
    const decided = screen.getAllByTestId("v2-point").find((r) => r.textContent?.includes("Tag"))!;
    expect(within(decided).getByTestId("v2-state")).toHaveTextContent("Kept by Sana");
    expect(within(decided).queryByRole("button", { name: "Keep" })).toBeNull();
    fireEvent.click(within(decided).getByRole("button", { name: "Change" }));
    expect(within(decided).getByRole("button", { name: "Keep" })).toBeInTheDocument();
  });
  it("repeated questions are ONE group: Question · 4 alike, Keep all, Open the 4", async () => {
    api.keepAll.mockResolvedValue(ok(listing()));
    mount(); await loaded();
    const group = screen.getByTestId("v2-group");
    expect(within(group).getByTestId("v2-pill")).toHaveTextContent("Question · 4 alike");
    expect(within(group).queryAllByTestId("v2-point")).toHaveLength(0);
    fireEvent.click(within(group).getByRole("button", { name: "Keep all" }));
    await waitFor(() => expect(api.keepAll).toHaveBeenCalledWith("doc1", ["ai:r:q1", "ai:r:q2", "ai:r:q3", "ai:r:q4"]));
    fireEvent.click(within(group).getByRole("button", { name: "Open the 4" }));
    expect(within(group).getAllByTestId("v2-point")).toHaveLength(4);
  });
});

describe("9 an opened point", () => {
  it("shows the action line and two boxes side by side with only checked text and the View page link", async () => {
    mount(); await loaded();
    fireEvent.click(within(screen.getAllByTestId("v2-point")[0]).getByRole("button", { name: /Design pressure/ }));
    const open = screen.getByTestId("v2-open-point");
    expect(open).toHaveTextContent("Contractor to revise the design pressure");
    const paper = within(open).getByTestId("v2-paper-box");
    const clause = within(open).getByTestId("v2-clause-box");
    expect(paper).toHaveTextContent("The paper, page 4");
    expect(paper).toHaveTextContent("2.2 bar (ga)");
    expect(paper).toHaveTextContent("Checked by code: found on the page.");
    expect(clause).toHaveTextContent("API 610, clause 6.2");
    expect(clause).toHaveTextContent("The design pressure shall be 6,900 kPa.");
    expect(clause).toHaveTextContent("Checked by code: found in the clause.");
    fireEvent.click(within(paper).getByRole("button", { name: "View page" }));
    expect(screen.getByTestId("viewer")).toHaveTextContent("viewer at page 4");
  });
  it("an unverified or missing quote shows no text, only the plain line", async () => {
    mount(); await loaded();
    fireEvent.click(within(screen.getAllByTestId("v2-point")[1]).getByRole("button", { name: /Material/ }));
    const paper = screen.getByTestId("v2-paper-box");
    expect(paper.querySelector("blockquote")).toBeNull();
    expect(paper).toHaveTextContent("No verified quote from the paper for this point.");
    expect(screen.getByTestId("v2-open-point")).toHaveTextContent("Two readers reached this verdict independently.");
  });
  it("says who decided: a view stays the AI's until a person keeps it", async () => {
    mount(); await loaded();
    fireEvent.click(within(screen.getAllByTestId("v2-point")[0]).getByRole("button", { name: /Design pressure/ }));
    expect(screen.getByTestId("v2-open-point")).toHaveTextContent("AI review · AI reviewer on Claude · Not decided");
  });
});

describe("10 add a point", () => {
  it("takes the engineer's text with optional page, rule book and clause", async () => {
    api.add.mockResolvedValue(ok(listing()));
    mount(); await loaded();
    fireEvent.click(screen.getByTestId("v2-add-open"));
    expect(screen.getByRole("button", { name: "Add this point" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Your comment"), { target: { value: "Check the nozzle schedule." } });
    fireEvent.change(screen.getByLabelText(/Page \(optional\)/), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText(/Rule book \(optional\)/), { target: { value: "API 610" } });
    fireEvent.click(screen.getByRole("button", { name: "Add this point" }));
    await waitFor(() => expect(api.add).toHaveBeenCalledWith("doc1", { text: "Check the nozzle schedule.", page: 3, rule_book: "API 610" }));
  });
  it("an added point shows Added by and is decided by definition", async () => {
    mount(); await loaded();
    const added = screen.getAllByTestId("v2-point").find((r) => r.textContent?.includes("Check the P&ID"))!;
    expect(within(added).getByTestId("v2-pill")).toHaveTextContent("Added by Sana");
    expect(within(added).queryByRole("button", { name: "Keep" })).toBeNull();
  });
});

describe("11 the bottom row", () => {
  it("greys Sign and issue and says why, with counts", async () => {
    mount(); await loaded();
    expect(screen.getByTestId("v2-sign")).toBeDisabled();
    expect(screen.getByTestId("v2-sign-waits")).toHaveTextContent("Sign and issue waits: 7 points are not decided yet, and the review code is not recorded.");
  });
  it("enables it when every point is decided and the code is recorded", async () => {
    api.list.mockResolvedValue(ok(listing({ decided: 9, of: 9, final_code: "Approved with Comments" })));
    const { props } = mount(); await loaded();
    expect(screen.queryByTestId("v2-sign-waits")).toBeNull();
    fireEvent.click(screen.getByTestId("v2-sign"));
    expect(props.onSign).toHaveBeenCalled();
  });
  it("adds the server's other reasons to the line", () => {
    expect(signWaits({ undecided: 0, codeRecorded: true, blockers: ["2 pages are not read"] })).toBe("Sign and issue waits: 2 pages are not read.");
    expect(signWaits({ undecided: 0, codeRecorded: true })).toBeNull();
  });
  it("downloads the two copies of both reviewers and says what the contractor file holds", async () => {
    mount(); await loaded();
    fireEvent.click(screen.getByRole("button", { name: "CRS for your team" }));
    await waitFor(() => expect(api.downloadCrs).toHaveBeenCalledWith("rc1", "internal"));
    expect(api.downloadAgentCrs).toHaveBeenCalledWith("ai1", "internal");
    fireEvent.click(screen.getByRole("button", { name: "CRS for the contractor (working copy, not issued)" }));
    await waitFor(() => expect(api.downloadAgentCrs).toHaveBeenCalledWith("ai1", "contractor"));
    expect(api.downloadCrs).not.toHaveBeenCalledWith("rc1", "issue"); // the one issuing path signs; nothing else asks for it
    expect(screen.getByTestId("v2-contractor-line")).toHaveTextContent("never carries an AI wording");
  });
  it("says what the contractor file holds from the backend's own answer, in both states, never a fixed claim", async () => {
    const words = "The contractor file holds what code proved, your own words, and the AI's not-met verdicts that two readers agreed on, which this kind of paper allows.";
    api.list.mockResolvedValue(ok(listing({ contractor_copy: { kind: "datasheet", words } })));
    const first = mount(); await loaded();
    expect(screen.getByTestId("v2-contractor-line")).toHaveTextContent(words);
    expect(screen.getByTestId("v2-contractor-line")).not.toHaveTextContent("never carries an AI wording");
    first.unmount();
    api.list.mockResolvedValue(ok(listing()));
    mount(); await loaded();
    expect(screen.getByTestId("v2-contractor-line")).toHaveTextContent("never carries an AI wording");
  });
  it("the contractor button says it is the working copy, and after signing still not the issued file", async () => {
    mount({ signed: true }); await loaded();
    expect(screen.getByRole("button", { name: "CRS for the contractor (working copy)" })).toBeInTheDocument();
  });
  it("without an AI review the contractor button waits for signing and says so", async () => {
    api.list.mockResolvedValue(ok(listing({ runs: { rule_check: "rc1", ai_review: null } })));
    mount(); await loaded();
    expect(screen.getByRole("button", { name: "CRS for the contractor (working copy, not issued)" })).toBeDisabled();
    expect(screen.getByTestId("v2-contractor-line")).toHaveTextContent("made when you sign and issue");
  });
});

describe("no code words", () => {
  it("the page text, with code-looking data underneath, carries no id, no GREEN or RED and no model name", async () => {
    const l = listing();
    l.points[0] = point({ name: "Design pressure", id: "ai:6f5c1f4e-1111-2222-3333-444455556666:R-614e60d6" });
    api.list.mockResolvedValue(ok(l));
    const { container } = mount(); await loaded();
    fireEvent.click(within(screen.getAllByTestId("v2-point")[0]).getByRole("button", { name: /Design pressure/ }));
    const clone = container.cloneNode(true) as HTMLElement;
    clone.querySelector('[data-testid="v2-engine"]')?.remove(); // the engine line names the engine the owner chose (Claude)
    clone.querySelectorAll('[data-testid="v2-open-point"] p:last-child').forEach((n) => n.remove()); // the "AI reviewer on Claude" source line
    const text = clone.textContent ?? "";
    expect(text).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/);
    expect(text).not.toMatch(/\bR-614e60d6\b/);
    expect(hasBannedWord(text)).toBe(false);
  });
});

describe("U5 polish: chips by book, names without tags, groups with pages, Claude not available", () => {
  const withBooks = (over: Partial<ReviewPoint>, ids: string[]) => point({ books: ids.map((id) => ({ id, name: id === "d1" ? "Book One" : "Book Two" })), no_book: ids.length === 0, ...over });
  const bookListing = () => listing({
    points: [
      withBooks({ id: "p1", name: "Set pressure" }, ["d1"]),
      withBooks({ id: "p2", name: "Orifice", rule_book: "Book Two" }, ["d2"]),
      withBooks({ id: "p3", name: "Capacity", rule_book: "Book One" }, ["d1", "d2"]),
      withBooks({ id: "p4", name: "Free comment", rule_book: null, clause: null }, []),
    ],
    counts: { ...listing().counts, rule_books: [{ id: "d1", name: "Book One", points: 2 }, { id: "d2", name: "Book Two", points: 2 }], no_rule_book_points: 1, other_rule_books_points: 0 },
  });

  it("one chip per rule book with its real name and count, plus No rule book; a chip filters by the book's identity", async () => {
    api.list.mockResolvedValue(ok(bookListing()));
    mount(); await loaded();
    const chips = screen.getByTestId("v2-books");
    expect(within(chips).getAllByRole("button").map((b) => b.textContent)).toEqual(["All rule books", "Book One (2)", "Book Two (2)", "No rule book (1)"]);
    fireEvent.click(within(chips).getByRole("button", { name: "Book Two (2)" }));
    expect(screen.getAllByTestId("v2-point").map((r) => r.textContent)).toHaveLength(2); // the point that cites both books is in both chips
    fireEvent.click(within(chips).getByRole("button", { name: "No rule book (1)" }));
    expect(screen.getAllByTestId("v2-point")).toHaveLength(1);
    expect(screen.getByTestId("v2-point")).toHaveTextContent("Free comment");
  });

  it("a name carries no tag list; the opened point says 'Applies to: N tags' and expands to the list", async () => {
    api.list.mockResolvedValue(ok(listing({ points: [point({ id: "t1", name: "Set pressure", tags: ["TG-1", "TG-2", "TG-3"] })] })));
    mount(); await loaded();
    const row = screen.getByTestId("v2-point");
    expect(row.textContent).not.toMatch(/TG-/);
    fireEvent.click(within(row).getByRole("button", { name: /Set pressure/ }));
    const tags = screen.getByTestId("v2-tags");
    expect(tags).toHaveTextContent("Applies to: 3 tags");
    expect(tags.tagName).toBe("DETAILS");
    expect(tags).toHaveTextContent("TG-1, TG-2, TG-3");
  });

  it("a group lists the pages it stands on", async () => {
    mount(); await loaded();
    expect(screen.getByTestId("v2-group-place")).toHaveTextContent("pages 3, 4, 5, 6");
  });

  it("when Claude is not available the engine line says so, the Claude choice is disabled with the reason, and no cost is promised", async () => {
    api.plan.mockResolvedValue(ok(plan({ claude_standing_refusal: { cause: "usage_limit", words: "the Claude account's usage limit is reached", at: "2026-11-12T14:00:00+00:00" } })));
    mount(); await loaded();
    const line = await screen.findByTestId("v2-engine-line");
    expect(line).toHaveTextContent("Claude is not available now (the Claude account's usage limit is reached), so Automatic runs on this computer.");
    expect(line.textContent).not.toMatch(/leave this computer|Cost:/);
    const claude = screen.getByRole("radio", { name: "Claude" });
    expect(claude).toBeDisabled();
    expect(claude).toHaveAttribute("title", "Claude is not available now (the Claude account's usage limit is reached)");
    expect(screen.getByRole("button", { name: "Review" })).toBeEnabled();
  });

  it("with Claude available the engine line is as before", async () => {
    mount(); await loaded();
    expect(screen.getByRole("radio", { name: "Claude" })).toBeEnabled();
    expect(await screen.findByTestId("v2-engine-line")).toHaveTextContent("will leave this computer");
  });
});
