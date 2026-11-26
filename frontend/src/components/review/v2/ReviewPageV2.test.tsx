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
  list: vi.fn(), plan: vi.fn(), decide: vi.fn(), keepAll: vi.fn(), add: vi.fn(), start: vi.fn(), confirmNa: vi.fn(), undoNa: vi.fn(),
  general: vi.fn(), method: vi.fn(), history: vi.fn(), downloadGeneral: vi.fn(),
  ofDocument: vi.fn(), kinds: vi.fn(), confirmKind: vi.fn(), decideCode: vi.fn(), downloadCrs: vi.fn(), downloadAgentCrs: vi.fn(), downloadPaperCrs: vi.fn(),
};
vi.mock("../../../api/reviewPoints", async (orig) => ({
  ...(await orig<typeof import("../../../api/reviewPoints")>()),
  reviewPoints: {
    list: (...a: unknown[]) => api.list(...a), plan: (...a: unknown[]) => api.plan(...a), decide: (...a: unknown[]) => api.decide(...a),
    keepAll: (...a: unknown[]) => api.keepAll(...a), add: (...a: unknown[]) => api.add(...a), start: (...a: unknown[]) => api.start(...a),
    confirmNotApplicable: (...a: unknown[]) => api.confirmNa(...a), undoNotApplicable: (...a: unknown[]) => api.undoNa(...a),
  },
}));
vi.mock("../../../api/generalReview", () => ({
  generalReview: { get: (...a: unknown[]) => api.general(...a), method: (...a: unknown[]) => api.method(...a), history: (...a: unknown[]) => api.history(...a) },
  downloadGeneralSheet: (...a: unknown[]) => api.downloadGeneral(...a),
}));
vi.mock("../../../api/documents", () => ({
  classification: {
    ofDocument: (...a: unknown[]) => api.ofDocument(...a), kinds: (...a: unknown[]) => api.kinds(...a),
    confirmKind: (...a: unknown[]) => api.confirmKind(...a),
  },
}));
vi.mock("../../../api/client", () => ({ reviews: { decideCode: (...a: unknown[]) => api.decideCode(...a) } }));
vi.mock("../downloadCrs", () => ({ downloadCrs: (...a: unknown[]) => api.downloadCrs(...a) }));
vi.mock("../agent/downloadAgentCrs", () => ({
  downloadAgentCrs: (...a: unknown[]) => api.downloadAgentCrs(...a), downloadPaperCrs: (...a: unknown[]) => api.downloadPaperCrs(...a),
}));
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
    proposed_code: { code: null, reason: "A code that lets the paper proceed is proposed only when every point is decided: a point still to decide may hold a failure.", line: "No review code proposed yet: 7 of 9 points still to decide.", so_far: true, undecided: 7, rule: "r", proposed_by: "the system; the engineer decides" },
    final_code: null, code_run_id: "rc1", decided: 2, of: 9, removed: [],
    contractor_copy: { kind: "datasheet", words: "The contractor file holds only what code proved, or your own words. It never carries an AI wording." }, ...over,
  };
}

const plan = (over: Partial<ReviewPlan> = {}): ReviewPlan => ({
  choice: "automatic", parts: [{ name: "rule_check", engine: "claude", why: "x" }, { name: "ai_review", engine: "claude", why: "y" }],
  text_leaves: true, refused: null, refused_code: null, needs_yes: false, unscored: false, wont_run: [], kind: "datasheet",
  documents: {
    paper: true, rule_books: ["API 610", "Other Book", "Third", "Fourth"], rule_books_note: null,
    leaving: [
      { id: "doc1", title: "Pump datasheet.pdf", kind: "paper", why: "paper under review", contract: false },
      { id: "bk1", title: "API 610 rule book.pdf", kind: "rule book", why: "cited by the paper", contract: false },
    ],
    not_sent: [{ name: "API 999", kind: "rule book", why: "cited by the paper", reason: "not held in the library" }],
    not_readable: 1,
  },
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

const NO_GENERAL = { ok: false, disconnected: false, error: { code: "not_found", message: "this paper has no general review" } };

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  api.general.mockResolvedValue(NO_GENERAL);
  api.method.mockResolvedValue(ok({ method: "earlier" }));
  api.history.mockResolvedValue(ok({ paper_document_id: "doc1", boundary: "reviews of this paper you may read", runs: [] }));
  api.downloadGeneral.mockResolvedValue(null);
  api.list.mockResolvedValue(ok(listing()));
  api.plan.mockResolvedValue(ok(plan()));
  api.ofDocument.mockResolvedValue(ok({ document_kind: "datasheet", document_kind_state: "suggested", equipment_type: "pressure_relief_valve" }));
  api.kinds.mockResolvedValue(ok({ kinds: [{ id: "datasheet", label: "Datasheet" }] }));
  api.downloadCrs.mockResolvedValue(null);
  api.downloadAgentCrs.mockResolvedValue(null);
  api.downloadPaperCrs.mockResolvedValue(null);
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
    await waitFor(() => expect(api.start).toHaveBeenCalledWith("doc1", "local", []));
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
    // H1: a note beside a null cost now says the cost was NOT READ, so "no earlier review" has no note either
    expect(costWords(plan({ cost: { ...plan().cost, last_review_usd: null, last_review_note: null } }))).toBe("Cost: limit USD 30");
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
  it("a contract paper on Automatic says Automatic keeps it here and to choose Claude; there is no yes button any more", async () => {
    api.plan.mockResolvedValue(ok(plan({ needs_yes: true })));
    mount(); await loaded();
    expect(await screen.findByTestId("v2-needs-yes")).toHaveTextContent("choose Claude to send it to Claude");
    expect(screen.queryByRole("button", { name: "Record the owner's yes" })).toBeNull();
  });
  it("the words come from one place", () => {
    expect(engineWords(plan({ text_leaves: true }))).toContain("will leave this computer");
    expect(wontRunWords(plan({ wont_run: [{ part: "contract checklist", why: "empty; an engineer must write it" }] }))).toEqual(["contract checklist: empty; an engineer must write it."]);
  });
});

describe("3 the review code box", () => {
  it("shows the proposed code, ONE line of reason and x of N decided", async () => {
    mount(); await loaded();
    // order 14: the server's shape while points are open (no approving code is proposed; `review_code_proposal`)
    expect(screen.getByTestId("v2-code-line")).toHaveTextContent("No review code proposed yet: 7 of 9 points still to decide.");
    expect(screen.getByTestId("v2-code-reason")).toHaveTextContent("proposed only when every point is decided");
    expect(screen.getByText("proposed by the system; you decide")).toBeInTheDocument();
    expect(screen.getByTestId("v2-decided")).toHaveTextContent("2 of 9 decided");
  });
  it("records the final code, asking why when it is not the proposed one", async () => {
    // a code is proposed only once every point is decided (order 14): the listing of a fully decided review
    api.list.mockResolvedValue(ok(listing({
      proposed_code: { code: "Approved with Comments", reason: "2 kept comments; none is proven by code to fail a 'shall' rule.", line: "Approved with Comments", so_far: false, undecided: 0, rule: "r", proposed_by: "the system; the engineer decides" },
      decided: 9, of: 9,
    })));
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

describe("3b the recorded code while points are open (order 14)", () => {
  it("preselects nothing, and an approving code with points still to decide asks why before it is sent", async () => {
    api.decideCode.mockResolvedValue(ok({}));
    mount(); await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Record the code" }));
    expect((screen.getByLabelText("Final code") as HTMLSelectElement).value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Record final code" }));
    expect(await screen.findByText("Choose a code first.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Final code"), { target: { value: "Approved" } });
    expect(screen.getByLabelText("Why it may proceed with points still to decide")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Record final code" }));
    expect(await screen.findByText("A reason is needed: 7 of 9 points are still to decide.")).toBeInTheDocument();
    expect(api.decideCode).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Why it may proceed with points still to decide"), { target: { value: "invented reason" } });
    fireEvent.click(screen.getByRole("button", { name: "Record final code" }));
    await waitFor(() => expect(api.decideCode).toHaveBeenCalledWith("rc1", "Approved", "invented reason"));
  });
  it("a code that lets nothing proceed needs no reason while points are open", async () => {
    mount(); await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Record the code" }));
    fireEvent.change(screen.getByLabelText("Final code"), { target: { value: "Rejected / Revise and Resubmit" } });
    expect(screen.queryByLabelText("Why it may proceed with points still to decide")).toBeNull();
  });
  it("the recorded code is printed as the server words it", async () => {
    api.list.mockResolvedValue(ok(listing({ final_code: "Approved", final_code_words: { team: "Approved (recorded with 7 of 9 points still to decide: invented reason)", contractor: "Approved (recorded by the engineer)" } })));
    mount(); await loaded();
    expect(screen.getByText(/Recorded final code: Approved \(recorded with 7 of 9 points still to decide: invented reason\)/)).toBeInTheDocument();
  });
});

describe("4 the four tiles", () => {
  it("each is a big number with one small line; a count the review cannot have is not shown", async () => {
    mount(); await loaded();
    expect(screen.getByTestId("v2-tile-not_met")).toHaveTextContent("3");
    expect(screen.getByTestId("v2-tile-not_met")).toHaveTextContent("1 two readers · 1 AI, engineer to confirm · 1 proven by code");
    expect(screen.getByTestId("v2-tile-questions")).toHaveTextContent("in 2 groups");
    expect(screen.getByTestId("v2-tile-does_not_apply")).toHaveTextContent("0");
    expect(tileLine("does_not_apply", { label: "x", total: 0, proven_by_code: null })).toBe("");
    expect(tileLine("not_met", { label: "x", total: 2, two_readers: null, one_reader: 2, proven_by_code: 0 })).toBe("2 AI, engineer to confirm");
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
    expect(screen.getByTestId("v2-firm")).toHaveTextContent("2 proven by code, 1 agreed by two readers, 1 AI answers, engineer to confirm. A person decides each point.");
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
  it("shows no online line while the online search is off (no found_online in the listing)", async () => {
    mount(); await loaded();
    expect(screen.queryByTestId("v2-found-online")).toBeNull();
  });
  it("with the online search on, says what it found, marked not verified, one line per book", async () => {
    const l = listing();
    l.counts.not_held = {
      ...l.counts.not_held,
      found_online: [
        { name: "Book A", outcome: "found", words: "Book A title; 7th edition; (2020); Publisher (found online, not verified; the book is not held)", url: null },
        { name: "Book B", outcome: "not searched", words: "not searched: not a public standard name, so it was not sent", url: null },
      ],
    };
    api.list.mockResolvedValue(ok(l));
    mount(); await loaded();
    const lines = within(screen.getByTestId("v2-found-online")).getAllByRole("listitem");
    expect(lines).toHaveLength(2);
    expect(lines[0]).toHaveTextContent("Found online (not verified, book not held): Book A: Book A title; 7th edition; (2020); Publisher (found online, not verified; the book is not held)");
    expect(lines[1]).toHaveTextContent("Book B: not searched: not a public standard name, so it was not sent");
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
  it("each button downloads ONE file of the paper, and says what the contractor file holds", async () => {
    mount(); await loaded();
    fireEvent.click(screen.getByRole("button", { name: "CRS for your team" }));
    await waitFor(() => expect(api.downloadPaperCrs).toHaveBeenCalledWith("doc1", "team"));
    fireEvent.click(screen.getByRole("button", { name: "CRS for the contractor (working copy, not issued)" }));
    await waitFor(() => expect(api.downloadPaperCrs).toHaveBeenCalledWith("doc1", "contractor"));
    expect(api.downloadPaperCrs).toHaveBeenCalledTimes(2);
    expect(api.downloadCrs).not.toHaveBeenCalled();
    expect(api.downloadAgentCrs).not.toHaveBeenCalled();
    expect(screen.getByTestId("v2-contractor-line")).toHaveTextContent("the failures code proved that you kept, and the points whose words are yours");
  });
  it("keeps the older per-run files under How it was reviewed", async () => {
    mount(); await loaded();
    fireEvent.click(screen.getByRole("tab", { name: "How it was reviewed" }));
    fireEvent.click(screen.getByRole("button", { name: "Rule check, internal copy" }));
    await waitFor(() => expect(api.downloadCrs).toHaveBeenCalledWith("rc1", "internal"));
    fireEvent.click(screen.getByRole("button", { name: /AI review, contractor working copy/ }));
    await waitFor(() => expect(api.downloadAgentCrs).toHaveBeenCalledWith("ai1", "contractor"));
  });
  it("says how many comments the CRS file holds, from the backend's own count", async () => {
    api.list.mockResolvedValue(ok(listing({ comment_count: 3 })));
    mount(); await loaded();
    expect(screen.getByTestId("v2-comment-count")).toHaveTextContent("as 3 comments");
  });
  it("shows a banner naming what is missing when the three counts differ, and nothing when they agree", async () => {
    const bad = { ok: false, page: 3, database: 4, team_rows: 3, contractor_rows: 0, missing: ["an AI line (Design pressure, page 2) is stored but not on the page"], sentence: "x", checked_at: "t" };
    api.list.mockResolvedValue(ok(listing({ completeness: bad })));
    const first = mount(); await loaded();
    expect(screen.getByTestId("v2-incomplete")).toHaveTextContent("Design pressure, page 2");
    expect(screen.getByTestId("v2-incomplete")).toHaveTextContent("the page has 3 points, the database 4 lines");
    first.unmount();
    api.list.mockResolvedValue(ok(listing({ completeness: { ...bad, ok: true, missing: [] } })));
    mount(); await loaded();
    expect(screen.queryByTestId("v2-incomplete")).toBeNull();
  });
  it("the contractor button says it is the working copy, and after signing still not the issued file", async () => {
    mount({ signed: true }); await loaded();
    expect(screen.getByRole("button", { name: "CRS for the contractor (working copy)" })).toBeInTheDocument();
  });
  it("without an AI review the contractor button still gives the working copy and says so", async () => {
    api.list.mockResolvedValue(ok(listing({ runs: { rule_check: "rc1", ai_review: null } })));
    mount(); await loaded();
    expect(screen.getByRole("button", { name: "CRS for the contractor (working copy, not issued)" })).toBeEnabled();
    expect(screen.getByTestId("v2-contractor-line")).toHaveTextContent("working copy until you sign and issue");
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

describe("U5 polish: chips by book, names without tags, groups with pages, books counted once or said twice", () => {
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

  it("says that a point citing two books is counted under each", async () => {
    const l = bookListing();
    l.counts = { ...l.counts, several_books_points: 1 };
    api.list.mockResolvedValue(ok(l));
    mount(); await loaded();
    expect(screen.getByTestId("v2-several-books")).toHaveTextContent("1 point cites more than one rule book and is counted under each.");
  });
  it("says nothing of it when no point cites two books", async () => {
    api.list.mockResolvedValue(ok(bookListing()));
    mount(); await loaded();
    expect(screen.queryByTestId("v2-several-books")).toBeNull();
  });

  it("a row and a group show their tag count, so alike names with different tag sets can be told apart before opening", async () => {
    api.list.mockResolvedValue(ok(listing({ points: [
      point({ id: "t1", name: "Set pressure", tags: ["TG-1", "TG-2", "TG-3", "TG-4"] }),
      point({ id: "t2", name: "Set pressure", rank: 2, tile: "not_met", tags: ["TG-5"] }),
      alike(1), alike(2),
    ].map((p, i) => (i >= 2 ? { ...p, tags: [`TG-${10 + i}`, `TG-${20 + i}`] } : p)) })));
    mount(); await loaded();
    const rows = screen.getAllByTestId("v2-point");
    expect(rows[0]).toHaveTextContent("4 tags");
    expect(rows[1]).toHaveTextContent("1 tag");
    expect(rows[0].textContent).not.toMatch(/TG-/);
    expect(screen.getByTestId("v2-group-place")).toHaveTextContent("4 tags in all");
  });

  it("a group says what its members differ in, so Keep all is not blind", async () => {
    const mk = (i: number, q: string | null) => ({ ...alike(i), paper_quote: q });
    api.list.mockResolvedValue(ok(listing({ points: [mk(1, "2.2 bar"), mk(2, "3.0 bar"), mk(3, "2.2 bar"), mk(4, null)] })));
    mount(); await loaded();
    expect(screen.getByTestId("v2-group-values")).toHaveTextContent("Values in the paper: 2.2 bar / 3.0 bar");
  });
  it("a group whose members show the same value, or none, says nothing of values; many values are counted", async () => {
    api.list.mockResolvedValue(ok(listing({ points: [1, 2, 3, 4].map((i) => ({ ...alike(i), paper_quote: "2.2 bar" })) })));
    const { unmount } = mount(); await loaded();
    expect(screen.queryByTestId("v2-group-values")).toBeNull();
    unmount();
    api.list.mockResolvedValue(ok(listing({ points: [1, 2, 3, 4].map((i) => ({ ...alike(i), paper_quote: `value number ${i}` })) })));
    mount(); await loaded();
    expect(screen.getByTestId("v2-group-values")).toHaveTextContent("4 different values in the paper");
  });
});

describe("11 the list of documents that leave, before the start (owner, 12 Nov 2026, #1584)", () => {
  const titles = () => screen.getByTestId("v2-leaving");

  it("shows the list from the plan with the engine line, before anything starts", async () => {
    mount(); await loaded();
    expect(await screen.findByText("These documents will be sent to Claude")).toBeInTheDocument();
    expect(within(titles()).getByText("API 610 rule book.pdf")).toBeInTheDocument();
    expect(within(titles()).getByText(/not held in the library/)).toBeInTheDocument();
    expect(within(titles()).getByText(/1 more document\(s\) cited are ones you may not read/)).toBeInTheDocument();
    expect(api.start).not.toHaveBeenCalled();
  });

  it("Review opens the step first; Start sends exactly the ids shown through the one start", async () => {
    api.start.mockResolvedValue(ok({ review_run_id: "run-new" }));
    const { props } = mount(); await loaded();
    await screen.findByTestId("v2-leaving");
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    const step = await screen.findByTestId("v2-prestart");
    expect(api.start).not.toHaveBeenCalled(); // the step is first
    expect(within(step).getByText("Pump datasheet.pdf")).toBeInTheDocument();
    expect(within(step).getByText(/together at most|Cost: about USD 0.50, limit USD 30/)).toBeInTheDocument();
    fireEvent.click(within(step).getByRole("button", { name: "Start" }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith("doc1", "automatic", ["doc1", "bk1"]));
    await waitFor(() => expect(props.onOpenRun).toHaveBeenCalledWith("run-new"));
  });

  it("Cancel closes the step and starts nothing", async () => {
    mount(); await loaded();
    await screen.findByTestId("v2-leaving");
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("v2-prestart")).toBeNull();
    expect(api.start).not.toHaveBeenCalled();
  });

  it("fails closed: when the plan cannot be loaded, no Claude start is offered, and Local only starts at once with no list", async () => {
    api.plan.mockResolvedValue({ ok: false, error: { message: "plan failed" } });
    api.start.mockResolvedValue(ok({ review_run_id: "run-new" }));
    mount(); await loaded();
    expect(await screen.findByTestId("v2-failed-closed")).toHaveTextContent("Claude is not offered");
    expect(screen.getByRole("button", { name: "Review" })).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "Claude" }));
    expect(screen.getByRole("button", { name: "Review" })).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "Local only" }));
    expect(screen.getByRole("button", { name: "Review" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith("doc1", "local", []));
  });

  it("fails closed when the plan gives no list of documents (an older server) or says it could not work it out", async () => {
    api.plan.mockResolvedValue(ok(plan({ documents: { paper: true, rule_books: [], rule_books_note: null } })));
    mount(); await loaded();
    expect(await screen.findByTestId("v2-no-list")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review" })).toBeDisabled();
  });

  it("Local only says nothing leaves this Mac and starts without a step", async () => {
    api.plan.mockResolvedValue(ok(plan({
      choice: "local", text_leaves: false, cost: { ...plan().cost, at_most_usd: null },
      parts: [{ name: "rule_check", engine: "local", why: "z" }, { name: "ai_review", engine: "not_run", why: "x" }],
      documents: { paper: false, rule_books: [], rule_books_note: null, leaving: [], not_sent: [], not_readable: 0 },
    })));
    api.start.mockResolvedValue(ok({ review_run_id: "run-new" }));
    mount(); await loaded();
    fireEvent.click(screen.getByRole("radio", { name: "Local only" }));
    expect(await screen.findByText("Nothing leaves this Mac.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    expect(screen.queryByTestId("v2-prestart")).toBeNull();
    await waitFor(() => expect(api.start).toHaveBeenCalledWith("doc1", "local", []));
  });

  it("a contract on the list shows the one plain line before Start when Claude was chosen, and not on Automatic", async () => {
    const withContract = plan({
      documents: { ...plan().documents, leaving: [{ id: "doc1", title: "Supply contract.pdf", kind: "paper", why: "paper under review", contract: true }] },
    });
    api.plan.mockResolvedValue(ok(withContract));
    mount(); await loaded();
    await screen.findByTestId("v2-leaving");
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    expect(screen.queryByTestId("v2-contract-line")).toBeNull(); // Automatic is not a choice of Claude
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("radio", { name: "Claude" }));
    await waitFor(() => expect(api.plan).toHaveBeenLastCalledWith("doc1", "claude"));
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    expect(await screen.findByTestId("v2-contract-line")).toHaveTextContent(
      "This sends the contract's text to Claude (Anthropic). You chose Claude for this review.",
    );
  });

  it("a rule book found only during the review is said on the result, with the way to include it", async () => {
    api.list.mockResolvedValue(ok(listing({ found_during_review: 2 })));
    mount(); await loaded();
    expect(await screen.findByTestId("found-during-review")).toHaveTextContent(
      "2 more rule book(s) apply to this paper. They were not sent because they were not on the list you saw. Review again to include them.",
    );
  });

  it("nothing leaving on Automatic: Review starts at once with an empty list and no step (removing that shortcut must fail this)", async () => {
    api.plan.mockResolvedValue(ok(plan({
      text_leaves: false, cost: { ...plan().cost, at_most_usd: null },
      parts: [{ name: "rule_check", engine: "local", why: "z" }, { name: "ai_review", engine: "not_run", why: "x" }],
      documents: { paper: false, rule_books: [], rule_books_note: null, leaving: [], not_sent: [], not_readable: 0 },
    })));
    api.start.mockResolvedValue(ok({ review_run_id: "run-new" }));
    mount(); await loaded();
    await screen.findByTestId("v2-engine-line");
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    expect(screen.queryByTestId("v2-prestart")).toBeNull();
    await waitFor(() => expect(api.start).toHaveBeenCalledWith("doc1", "automatic", []));
  });

  it("out-of-order plans: an earlier choice answering late is never shown, Review waits for the plan of the choice on screen, and Start sends that choice with those ids", async () => {
    const answers: Record<string, (v: unknown) => void> = {};
    api.plan.mockImplementation((_id: string, engine: string) => new Promise((resolve) => { answers[engine] = resolve; }));
    api.start.mockResolvedValue(ok({ review_run_id: "run-new" }));
    mount(); await loaded();
    await waitFor(() => expect(answers.automatic).toBeDefined());
    fireEvent.click(screen.getByRole("radio", { name: "Claude" }));
    await waitFor(() => expect(answers.claude).toBeDefined());
    fireEvent.click(screen.getByRole("radio", { name: "Automatic" }));
    await waitFor(() => expect(api.plan).toHaveBeenCalledTimes(3));
    // the plan on screen is not yet the plan for Automatic: Review is not offered
    expect(screen.getByRole("button", { name: "Review" })).toBeDisabled();
    const contract = { id: "CONTRACT", title: "Supply contract.pdf", kind: "contract", why: "cited by the paper", contract: true };
    const forAutomatic = plan({ documents: { ...plan().documents, leaving: [{ id: "doc1", title: "Pump datasheet.pdf", kind: "paper", why: "paper under review", contract: false }] } });
    const forClaude = plan({ documents: { ...plan().documents, leaving: [{ id: "doc1", title: "Pump datasheet.pdf", kind: "paper", why: "paper under review", contract: false }, contract] } });
    // the LAST request (Automatic) answers first, the earlier one (Claude) answers late
    answers.automatic(ok(forAutomatic));
    await screen.findByTestId("v2-leaving");
    answers.claude(ok(forClaude));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText("Supply contract.pdf")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    fireEvent.click(await screen.findByRole("button", { name: "Start" }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith("doc1", "automatic", ["doc1", "bk1"].slice(0, 1)));
  });

  it("an opened point shows what the stored finding holds, as stored and not verified, with its reason and who checked it", async () => {
    api.list.mockResolvedValue(ok(listing({ points: [point({
      id: "s1", rank: 4, tile: "questions", firm: null, name: "Inlet rating", pill: "Question", paper_quote: null, clause_quote: null,
      paper_value: "Rating 150", rule_text: "Inlet rating shall be class 300", reason_words: "A value of the datasheet could not be settled.", checked_by: "Rule check: datasheet checklist",
    })] })));
    mount(); await loaded();
    fireEvent.click(within(screen.getByTestId("v2-point")).getByRole("button", { name: /Inlet rating/ }));
    expect(screen.getByTestId("v2-paper-stored")).toHaveTextContent("As stored (not verified by code): \u201cRating 150\u201d");
    expect(screen.getByTestId("v2-clause-stored")).toHaveTextContent("not verified by code");
    expect(screen.getByTestId("v2-reason")).toHaveTextContent("Checked by: Rule check: datasheet checklist.");
  });

  it("an opened point shows our checklist's own words as ours, never as the rule book's", async () => {
    api.list.mockResolvedValue(ok(listing({ points: [point({
      id: "s2", rank: 4, tile: "questions", firm: null, name: "Inlet rating", pill: "Question", paper_quote: null, clause_quote: null,
      rule_text: null, check_text: "Datasheet check PSV-05: The inlet rating is stated.",
    })] })));
    mount(); await loaded();
    fireEvent.click(within(screen.getByTestId("v2-point")).getByRole("button", { name: /Inlet rating/ }));
    expect(screen.getByTestId("v2-check-text")).toHaveTextContent("Our checklist asks (our words): \u201cDatasheet check PSV-05: The inlet rating is stated.\u201d");
    expect(screen.queryByTestId("v2-clause-stored")).toBeNull();
  });
});

// ---------------------------------------------------------------- owner on PR #1872: the AI thinks these do not apply, tick to confirm

describe("the section of lines the AI thinks do not apply", () => {
  const na = (i: number, book: string, state: "keep" | null = null) => point({
    id: `ai:r:na${i}`, rank: 9, tile: "na_to_confirm", firm: "to confirm", name: `Unproven field ${i}`, rule_book: book, clause: `${i}.1`,
    pill: "Does not apply (AI, engineer to confirm)", ai_label: "Does not apply (AI, engineer to confirm)", decision: state ? { state, words: "Does not apply (confirmed by the engineer)", by: "Sana" } : { state: null, words: "Not decided" },
  });
  const withSection = () => {
    const base = listing();
    return listing({
      points: [...base.points, na(1, "Book X"), na(2, "Book X", "keep"), na(3, "Book Y")],
      counts: { ...base.counts, not_applicable_to_confirm: { label: "AI thinks these do not apply, tick to confirm", total: 3, confirmed: 1, open: 2,
        sentence: "3 points the AI thinks do not apply, to confirm: 1 confirmed, 2 open." } },
    });
  };

  it("shows them in their own section, grouped, counted, and never in the main list", async () => {
    api.list.mockResolvedValue(ok(withSection()));
    mount();
    const section = await screen.findByTestId("v2-na-section");
    expect(within(section).getByText("AI thinks these do not apply, tick to confirm")).toBeInTheDocument();
    expect(within(section).getByTestId("v2-na-count")).toHaveTextContent("3 points the AI thinks do not apply, to confirm: 1 confirmed, 2 open.");
    expect(within(section).getAllByTestId("v2-na-group")).toHaveLength(2);
    expect(within(section).getAllByTestId("v2-na-line")).toHaveLength(3);
    expect(within(screen.getByTestId("v2-points")).queryByText(/Unproven field/)).toBeNull();
  });

  it("a tick confirms one line, unticking undoes it, and Confirm all ticks every open line", async () => {
    api.list.mockResolvedValue(ok(withSection()));
    api.confirmNa.mockResolvedValue(ok(withSection()));
    api.undoNa.mockResolvedValue(ok(withSection()));
    mount();
    const section = await screen.findByTestId("v2-na-section");
    fireEvent.click(within(section).getByLabelText("Confirm: Unproven field 1 does not apply"));
    await waitFor(() => expect(api.confirmNa).toHaveBeenCalledWith("doc1", ["ai:r:na1"]));
    fireEvent.click(within(section).getByLabelText("Confirm: Unproven field 2 does not apply"));
    await waitFor(() => expect(api.undoNa).toHaveBeenCalledWith("doc1", "ai:r:na2"));
    fireEvent.click(within(section).getByRole("button", { name: "Confirm all" }));
    await waitFor(() => expect(api.confirmNa).toHaveBeenLastCalledWith("doc1", ["ai:r:na1", "ai:r:na3"]));
  });

  it("is absent when there is no such line", async () => {
    mount();
    await screen.findByTestId("v2-points");
    expect(screen.queryByTestId("v2-na-section")).toBeNull();
  });
});

// ---------------------------------------------------------------- owner's item LP0 (17 Nov 2026): the AI's own answer, never a bare Query

describe("the AI's own answer on a line code did not prove", () => {
  const FAIL_AI = "Fail (AI, rule not approved, engineer to confirm)";
  const answered = point({
    id: "ai:r:R-3", rank: 4, tile: "questions", firm: null, name: "Invented field", pill: FAIL_AI, ai_label: FAIL_AI,
    ai_answer: `${FAIL_AI}: STD-A-001, clause 4.1, page 2; quote not found by code.`, paper_quote: null, clause_quote: null,
  });

  it("shows the label in the pill and, opened, the answer with standard, clause, page and quote", async () => {
    api.list.mockResolvedValue(ok(listing({ points: [answered] })));
    mount(); await loaded();
    const row = screen.getByTestId("v2-point");
    expect(within(row).getByTestId("v2-pill")).toHaveTextContent(FAIL_AI);
    expect(within(row).queryByText(/^Question$/)).toBeNull();
    fireEvent.click(within(row).getByRole("button", { name: /Invented field/ }));
    expect(screen.getByTestId("v2-ai-answer")).toHaveTextContent(`${FAIL_AI}: STD-A-001, clause 4.1, page 2; quote not found by code.`);
  });

  it("a point with no AI answer shows no answer line", async () => {
    api.list.mockResolvedValue(ok(listing({ points: [point({ id: "q1", rank: 4, tile: "questions", firm: null, name: "Asked field", pill: "Question" })] })));
    mount(); await loaded();
    fireEvent.click(within(screen.getByTestId("v2-point")).getByRole("button", { name: /Asked field/ }));
    expect(screen.queryByTestId("v2-ai-answer")).toBeNull();
  });

  it("an open line of the does-not-apply section says the owner's label until it is ticked", async () => {
    const na = point({
      id: "ai:r:na9", rank: 9, tile: "na_to_confirm", firm: null, name: "Unproven field 9", rule_book: "Book X",
      pill: "Does not apply (AI, engineer to confirm)", ai_label: "Does not apply (AI, engineer to confirm)",
    });
    const base = listing();
    api.list.mockResolvedValue(ok(listing({
      points: [...base.points, na],
      counts: { ...base.counts, not_applicable_to_confirm: { label: "AI thinks these do not apply, tick to confirm", total: 1, confirmed: 0, open: 1, sentence: null } },
    })));
    mount();
    const section = await screen.findByTestId("v2-na-section");
    expect(within(section).getByTestId("v2-na-line")).toHaveTextContent("Does not apply (AI, engineer to confirm) · not confirmed yet");
  });
});

// ---- order 14, piece C: the general review's results page ------------------------------------------------------------------------
import type { GeneralReview } from "../../../api/generalReview";

const MARK = "AI, to be checked";
function general(over: Partial<GeneralReview> = {}): GeneralReview {
  const line = (n: number, label: string, shown: string, page: number | null) => ({
    n, field: `Invented field ${n}`, page, label, shown_label: shown, comment: `invented comment ${n}`, quote: `invented quote ${n}`,
    item_id: `C0${n}`, standard: "STD-X", clause: `4.${n}`, source: "held standard",
  });
  const points = [line(1, "Not met", "Fail, compared by code", 4), line(2, "Met", "AI opinion: met", 5), line(3, "Question", "Question", null)];
  return {
    paper_document_id: "doc1", run_id: "g1", method: "aim-1", mark: MARK, status: "completed",
    identity: { kind: "datasheet", equipment_type: null, subject: "invented" },
    counts: { points: 3, comments: 2, by_label: { "Not met": 1, Met: 1, Question: 1 }, by_shown_label: { "Fail, compared by code": 1, "AI opinion: met": 1, Question: 1 }, boundary: "this paper, this review" },
    comments: [points[0], points[2]], points, books: [{ id: "bk1", title: "invented-book.pdf", why: "cited by the paper" }], books_not_readable: 1,
    not_held: [{ name: "Invented Public Standard", why: "cited, not held" }],
    unlisted_books: { count: 2, sentence: "2 more rule book(s) apply to this paper. They were not sent because they were not on the list you saw. Review again to include them." },
    checklist: { key: "k", items: 3, reused: true, built_from: "standards only, no paper" }, cost: { usd: 0.51 },
    completeness: { ok: true, page: 3, database: 3, file_rows: 3, sentence: null }, is_latest: true, ...over,
  };
}

describe("12 the general review's results page (order 14)", () => {
  it("counts the confirmations apart and shows them only in a closed part, not among the comments (18 Nov 2026)", async () => {
    const g = general();
    api.general.mockResolvedValue(ok({ ...g, counts: { ...g.counts, comments: 1, confirmations: 1 }, comments: [g.points[0]], confirmations: [g.points[2]] }));
    mount();
    const results = await screen.findByTestId("general-results");
    fireEvent.click(screen.getByRole("tab", { name: "How this review was made" })); // E5: the counts are folded (answer first)
    expect(screen.getByTestId("general-counts")).toHaveTextContent("3 points reviewed, 1 comments sent, 1 confirmations not sent");
    fireEvent.click(screen.getByRole("tab", { name: /^Comments/ }));
    const part = screen.getByTestId("general-confirmations");
    expect(part.tagName).toBe("DETAILS");
    expect(part).not.toHaveAttribute("open"); // closed until opened
    expect(within(part).getByText(/Confirmations, not sent \(1\)/)).toBeInTheDocument();
    const rows = within(results).getAllByTestId("general-row");
    expect(rows.filter((r) => !part.contains(r))).toHaveLength(1); // the comments sent: the confirmation is not among them
    expect(within(part).getAllByTestId("general-row")).toHaveLength(1);
  });


  it("H9: a general answer with card fields draws comment cards and the severity tiles on the page", async () => {
    const g = general();
    const withCard = (l: (typeof g.points)[number], severity: string, title: string) =>
      ({ ...l, severity, title, paper_says: "paper value", rule_says: "STD-X clause 4.1", we_ask: "please confirm it", applies_to: [{ page: l.page, field: l.field, quote: l.quote }], proven: "compared by code" });
    const comments = [withCard(g.points[0], "Must fix", "Invented problem one"), withCard(g.points[2], "Missing information", "Invented problem two")];
    api.general.mockResolvedValue(ok({ ...g, comments, counts: { ...g.counts, by_severity: { "Must fix": 1, "Missing information": 1 } } } as never));
    mount();
    await screen.findByTestId("general-results");
    expect(screen.getAllByTestId("card-title").map((t) => t.textContent)).toEqual(["Invented problem one", "Invented problem two"]);
    expect(screen.getByTestId("severity-tiles")).toHaveTextContent("Must fix");
  });

  it("draws the general results: the mark, the counts, the comments with page links, and no old sections", async () => {
    api.general.mockResolvedValue(ok(general()));
    mount();
    const results = await screen.findByTestId("general-results");
    expect(screen.getByTestId("general-mark")).toHaveTextContent(MARK);
    fireEvent.click(screen.getByRole("tab", { name: "How this review was made" })); // E5: the counts are folded (answer first)
    expect(screen.getByTestId("general-counts")).toHaveTextContent("3 points reviewed, 2 comments sent (this paper, this review)");
    fireEvent.click(screen.getByRole("tab", { name: /^Comments/ }));
    expect(screen.queryByTestId("general-confirmations")).toBeNull(); // an answer with no confirmations shows no such part
    const rows = within(results).getAllByTestId("general-row");
    expect(rows).toHaveLength(2); // the comments only, until "All points" is ticked
    rows.forEach((r) => expect(r).toHaveTextContent(MARK)); // the mark is on every row
    expect(rows[0]).toHaveTextContent("Fail, compared by code");
    expect(within(rows[0]).getByRole("button", { name: "page 4" })).toBeInTheDocument();
    expect(within(rows[1]).queryByRole("button", { name: /page/ })).toBeNull(); // a null page renders as nothing
    expect(screen.queryByTestId("v2-points")).toBeNull();
    expect(screen.queryByTestId("v2-code-box")).toBeNull();
  });

  it("the header names the equipment the AI named for this review, not another stored suggestion (first-time user: a vessel read 'Heat Exchanger')", async () => {
    const g = general();
    api.general.mockResolvedValue(ok({ ...g, identity: { kind: "datasheet", equipment_type: "pressure_vessel", subject: "invented vessel" } }));
    api.ofDocument.mockResolvedValue(ok({ document_id: "doc1", equipment_type: "heat_exchanger", confirmed: false, document_kind: "datasheet", document_kind_state: "guessed" } as never));
    mount();
    await screen.findByTestId("general-results");
    await waitFor(() => expect(screen.getByTestId("v2-kind-line")).toHaveTextContent("pressure vessel (named by the AI for this review)"));
    expect(screen.getByTestId("v2-kind-line")).not.toHaveTextContent("heat exchanger");
  });

  it("a finished general review hides the plan of a NEW review behind 'Review this paper again' and asks for no plan until it is opened", async () => {
    api.general.mockResolvedValue(ok(general()));
    api.plan.mockClear();
    mount();
    await screen.findByTestId("general-results");
    expect(screen.queryByText(/Checking what this would do/)).toBeNull();
    expect(screen.queryByTestId("v2-engine")).toBeNull();
    expect(api.plan).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("review-again"));
    expect(await screen.findByTestId("v2-engine")).toBeInTheDocument();
    await waitFor(() => expect(api.plan).toHaveBeenCalled());
  });

  it("has NO contractor button, NO sign row and NO review code; one Download button gives the team file", async () => {
    api.general.mockResolvedValue(ok(general()));
    mount(); await screen.findByTestId("general-results");
    expect(screen.queryByRole("button", { name: /contractor/i })).toBeNull();
    expect(screen.queryByTestId("v2-sign")).toBeNull();
    expect(screen.queryByTestId("v2-bottom")).toBeNull();
    expect(screen.queryByText(/Sign and issue/)).toBeNull();
    expect(screen.getAllByRole("button", { name: /Download/ })).toHaveLength(1);
    fireEvent.click(screen.getByTestId("general-download"));
    await waitFor(() => expect(api.downloadGeneral).toHaveBeenCalledWith("doc1", "g1"));
    expect(api.downloadPaperCrs).not.toHaveBeenCalled();
  });

  it("the All points toggle shows every point, and the server's refusal sentence is shown whole", async () => {
    api.general.mockResolvedValue(ok(general()));
    api.downloadGeneral.mockResolvedValue("This general review's file is not complete and was not given out: the page has 3 points, the database holds 4 lines.");
    mount(); await screen.findByTestId("general-results");
    fireEvent.click(screen.getByTestId("general-all-toggle"));
    expect(screen.getAllByTestId("general-row")).toHaveLength(3);
    fireEvent.click(screen.getByTestId("general-download"));
    expect(await screen.findByTestId("general-download-problem")).toHaveTextContent("the database holds 4 lines");
  });

  it("says when the counts differ, from the server's own sentence", async () => {
    api.general.mockResolvedValue(ok(general({ completeness: { ok: false, page: 3, database: 4, file_rows: 3, sentence: "This general review's file is not complete and was not given out: x." } })));
    mount();
    expect(await screen.findByTestId("general-incomplete")).toHaveTextContent("not complete and was not given out");
  });

  it("How it was reviewed holds the books, the books not held, the unlisted sentence and the history", async () => {
    api.general.mockResolvedValue(ok(general()));
    api.history.mockResolvedValue(ok({ paper_document_id: "doc1", boundary: "reviews of this paper you may read", runs: [
      { run_id: "g1", version: "general", part: "general review", status: "done", started_at: "t", finished_at: "2026-11-18T10:00:00Z", points: 3, files: [] },
      { run_id: "old1", version: "earlier version", part: "AI review", status: "completed", started_at: "t", finished_at: "2026-11-01T10:00:00Z", points: 9, files: [] },
    ] }));
    mount(); await screen.findByTestId("general-results");
    fireEvent.click(screen.getByRole("tab", { name: "How this review was made" }));
    expect(screen.getByTestId("general-how")).toHaveTextContent("invented-book.pdf");
    expect(screen.getByTestId("general-how")).toHaveTextContent("and 1 you may not open");
    expect(screen.getByTestId("general-how")).toHaveTextContent("Invented Public Standard");
    expect(screen.getByTestId("general-unlisted")).toHaveTextContent("2 more rule book(s) apply to this paper");
    const history = await screen.findByTestId("general-history");
    expect(history).toHaveTextContent("General review");
    expect(history).toHaveTextContent("Earlier version");
  });

  it("a page link opens the page viewer at that page", async () => {
    api.general.mockResolvedValue(ok(general()));
    mount(); await screen.findByTestId("general-results");
    fireEvent.click(screen.getByRole("button", { name: "page 4" }));
    expect(await screen.findByTestId("viewer")).toHaveTextContent("page 4");
  });

  it("a paper whose latest review is an earlier one keeps the old page, under the heading Earlier version", async () => {
    api.general.mockResolvedValue(ok(general({ is_latest: false })));
    mount(); await loaded();
    expect(screen.queryByTestId("general-results")).toBeNull();
    expect(screen.getByTestId("earlier-version")).toHaveTextContent("Earlier version");
    expect(screen.getByTestId("v2-sign")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "CRS for the contractor (working copy, not issued)" })).toBeInTheDocument();
  });

  it("a paper with no general review keeps the old page; the heading appears only while the general method is the one in use", async () => {
    mount(); await loaded();
    expect(screen.queryByTestId("general-results")).toBeNull();
    expect(screen.queryByTestId("earlier-version")).toBeNull(); // the old engine is the method: no label
    expect(screen.getByTestId("v2-sign")).toBeInTheDocument();
  });

  it("under the general method an old-only paper is labelled Earlier version", async () => {
    api.method.mockResolvedValue(ok({ method: "general" }));
    mount(); await loaded();
    expect(await screen.findByTestId("earlier-version")).toBeInTheDocument();
  });

  it("a stopped general review says so", async () => {
    api.general.mockResolvedValue(ok(general({ status: "stopped", stop_reason: "the spend limit was reached" })));
    mount();
    expect(await screen.findByTestId("general-stopped")).toHaveTextContent("the spend limit was reached");
  });
});

describe("13 the measured score of the paper's kind on the general results (order 14, piece G)", () => {
  it("shows the kind's measured score under the mark, and nothing when the run names no kind", async () => {
    const measured = { kind_label: "relief valve", found: 6.5, target: 7, verdict: "below target", sentence: "Invented: 6.5 of 10 found, below target" };
    api.general.mockResolvedValue(ok(general({ measured } as Partial<GeneralReview>)));
    mount();
    await screen.findByTestId("general-results");
    expect(screen.getByTestId("general-measured-sentence")).toHaveTextContent("6.5 of 10 found, below target");
  });

  it("shows no measured line for a run with no kind", async () => {
    api.general.mockResolvedValue(ok(general({ measured: null } as Partial<GeneralReview>)));
    mount();
    await screen.findByTestId("general-results");
    expect(screen.queryByTestId("general-measured-sentence")).toBeNull();
  });
});
