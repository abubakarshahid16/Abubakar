/**
 * Order 302.4 (d): the rule-approval screen. Tested is not approved; a stale screen decides nothing; the form
 * shows only what the rule's kind allows. Invented cards only.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { RuleCards, describeRule } from "./RuleCards";
import type { RuleCard, RuleCardListing } from "../../types/api";

const card: RuleCard = {
  card_id: "PSV-24", equipment_type: "Pressure Safety Valve", version: 1, content_hash: "h".repeat(64),
  state: "tested", why: "tested, not yet approved", weak_source: false,
  basis: "cases written from the rule's meaning, run on the real code", written_cases: 4,
  baseline_changed: false, versions: 1, decided_by: null, decided_at: null,
  item: {
    id: "PSV-24", text: "The set pressure is at most the MAWP.", severity: "critical",
    source: { standard: "API 520-I", clause: "5.4.2.1" },
    rule: { kind: "compare", left: "set_pressure", op: "<=", right: "mawp" },
  },
  cases: [
    { case: "meets", kind: "written", expected: "COMPLIANT", got: "COMPLIANT", passed: true },
    { case: "breaks", kind: "written", expected: "NON_COMPLIANT", got: "NON_COMPLIANT", passed: true },
  ],
};
const listing: RuleCardListing = {
  "Pressure Safety Valve": {
    cards: [
      { card_id: "PSV-24", text: card.item.text, source: card.item.source, state: "tested", why: "", version: 1,
        weak_source: false, written_cases: 4, decided_by: null, decided_at: null },
      { card_id: "PSV-05", text: "The relieving temperature is stated.", source: { standard: "API 520-I", clause: "3.43" },
        state: "draft", why: "needs a standard we do not hold", version: 1, weak_source: false, written_cases: 0,
        decided_by: null, decided_at: null },
    ],
    counts: { draft: 1, tested: 1, approved: 0, rejected: 0 },
    total: 2,
  },
};

function mock(posts: { url: string; body: unknown }[] = [], answer: { status: number; body: unknown } | null = null) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const json = (b: unknown, status = 200) => new Response(JSON.stringify(b),
      { status, headers: { "Content-Type": "application/json" } });
    if (init?.method === "POST") {
      posts.push({ url, body: JSON.parse(String(init.body)) });
      if (answer) return json(answer.body, answer.status);
      return json({ ...card, state: "approved", decided_by: "engineer@example.test", decided_at: "2026-10-29T00:00:00Z" });
    }
    return json(String(url).endsWith("/rule-cards") ? listing : card);
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe("RuleCards", () => {
  it("lists the cards per equipment type with a count per state and the total", async () => {
    mock();
    render(<RuleCards />);
    const group = await screen.findByTestId("rule-card-group-Pressure Safety Valve");
    expect(group).toHaveTextContent("2 cards of this equipment type");
    expect(group).toHaveTextContent("1 draft, 1 tested, not yet approved, 0 approved, 0 rejected");
    expect(group).toHaveTextContent("PSV-24: The set pressure is at most the MAWP.");
  });

  it("shows no group, and does not crash, for an answer of another shape", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([{ id: "x" }]),
      { status: 200, headers: { "Content-Type": "application/json" } })));
    render(<RuleCards />);
    expect(await screen.findByRole("heading", { name: /Rule cards/ })).toBeInTheDocument();
    expect(screen.queryByTestId(/rule-card-group-/)).toBeNull();
  });

  it("filters by state", async () => {
    mock();
    render(<RuleCards />);
    const group = await screen.findByTestId("rule-card-group-Pressure Safety Valve");
    fireEvent.change(screen.getByLabelText("Show"), { target: { value: "draft" } });
    expect(group).toHaveTextContent("PSV-05");
    expect(group).not.toHaveTextContent("PSV-24:");
  });

  it("shows a card in plain words with its cases, what tested rests on, and no approval it does not have", async () => {
    mock();
    render(<RuleCards />);
    fireEvent.click(await screen.findByRole("button", { name: /PSV-24/ }));
    const detail = await screen.findByTestId("rule-card-detail");
    expect(detail).toHaveTextContent("PSV-24: Tested, not yet approved");
    expect(detail).toHaveTextContent("The set pressure is at most the mawp.");
    expect(detail).toHaveTextContent("cases written from the rule's meaning");
    expect(within(detail).getByRole("table", { name: "Test cases" })).toHaveTextContent("passed");
    expect(detail).not.toHaveTextContent("Approved by");
  });

  it("approves the version it saw, with its hash, and then shows who approved", async () => {
    const posts: { url: string; body: unknown }[] = [];
    mock(posts);
    render(<RuleCards />);
    fireEvent.click(await screen.findByRole("button", { name: /PSV-24/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve this version" }));
    await waitFor(() => expect(screen.getByTestId("rule-card-detail")).toHaveTextContent("Approved by engineer@example.test"));
    expect(posts[0].body).toEqual({ version: 1, content_hash: "h".repeat(64), decision: "approved" });
    expect(posts[0].url).toContain("/rule-cards/PSV-24/decision");
  });

  it("says plainly when the card changed meanwhile and shows no approval", async () => {
    mock([], { status: 409, body: { detail: { code: "invalid_parameter", message: "this card changed since you opened it; reload it and decide again" } } });
    render(<RuleCards />);
    fireEvent.click(await screen.findByRole("button", { name: /PSV-24/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve this version" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("changed");
    expect(screen.getByTestId("rule-card-detail")).not.toHaveTextContent("Approved by");
  });

  it("will not offer to approve a card that is not tested", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(
      String(url).endsWith("/rule-cards") ? listing : { ...card, state: "draft", why: "a case failed" }),
      { status: 200, headers: { "Content-Type": "application/json" } })));
    render(<RuleCards />);
    fireEvent.click(await screen.findByRole("button", { name: /PSV-24/ }));
    const detail = await screen.findByTestId("rule-card-detail");
    expect(within(detail).getByRole("button", { name: "Approve this version" })).toBeDisabled();
    expect(detail).toHaveTextContent("Only a tested card can be approved.");
  });

  it("warns on a card tested by generated cases only", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(
      String(url).endsWith("/rule-cards") ? listing : { ...card, written_cases: 0, basis: "generated cases only: they check the code path" }),
      { status: 200, headers: { "Content-Type": "application/json" } })));
    render(<RuleCards />);
    fireEvent.click(await screen.findByRole("button", { name: /PSV-24/ }));
    expect(await screen.findByText(/generated cases cannot tell a right box from a wrong one/)).toBeInTheDocument();
  });

  it("sends only what changed when an engineer edits, and offers only the fields the rule has", async () => {
    const posts: { url: string; body: unknown }[] = [];
    mock(posts);
    render(<RuleCards />);
    fireEvent.click(await screen.findByRole("button", { name: /PSV-24/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const form = screen.getByRole("form", { name: "Edit the rule card" });
    expect(within(form).queryByLabelText("percent")).toBeNull();
    fireEvent.change(within(form).getByLabelText("Severity"), { target: { value: "minor" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save as a new version" }));
    await waitFor(() => expect(posts.length).toBe(1));
    expect(posts[0].body).toEqual({ version: 1, content_hash: "h".repeat(64), changes: { severity: "minor" } });
    expect(posts[0].url).toContain("/rule-cards/PSV-24/edit");
  });
});

describe("describeRule", () => {
  it("puts every kind of rule in words", () => {
    expect(describeRule({ kind: "required", field: "set_pressure" })).toBe("The set pressure is stated.");
    expect(describeRule({ kind: "percent_of", left: "built_up_back_pressure", op: "<=", percent: 10, right: "set_pressure" }))
      .toBe("The built up back pressure is at most 10% of the set pressure.");
    expect(describeRule({ kind: "above_by", left: "set_pressure", right: "operating_pressure", percent: 10, at_least: 100, unit: "kPa" }))
      .toBe("The set pressure is above the operating pressure by at least the greater of 10% or 100 kPa.");
    expect(describeRule({ kind: "allowed", field: "valve_type", values: ["conventional", "bellows"] }))
      .toBe("The valve type is one of: conventional, bellows.");
  });
});
