/**
 * The pre-start panel: the engine, whether text leaves the Mac, the cost and the list of documents come from the plan; the
 * start carries exactly the list shown; a plan that cannot be loaded offers no Claude start.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StartPanel } from "./StartPanel";

const plan = vi.fn();
vi.mock("../../../api/reviewPlan", () => ({
  reviewPlan: { plan: (...a: unknown[]) => plan(...a) },
}));

const claudePlan = {
  choice: "automatic",
  parts: [],
  text_leaves: true,
  refused: null,
  sentence: "The AI review runs on Claude. Text of this paper leaves this computer.",
  cost: { at_most_usd: 30, basis: "rule check: at most USD 15; AI review: at most USD 15; together at most USD 30" },
  documents: {
    leaving: [
      { id: "doc_1", title: "Pump datasheet rev B.pdf", kind: "paper", why: "paper under review" },
      { id: "doc_2", title: "API 610 rule book.pdf", kind: "rule book", why: "cited by the paper" },
    ],
    not_sent: [{ id: "doc_3", title: "Supply contract.pdf", kind: "contract", why: "cited by the paper", reason: "a contract goes only with the owner's recorded yes" }],
    not_readable: 1,
  },
};
const localPlan = {
  ...claudePlan, choice: "local", text_leaves: false, cost: { at_most_usd: null, basis: null },
  documents: { leaving: [], not_sent: [], not_readable: 0, summary: "Nothing leaves this Mac" },
};

beforeEach(() => {
  plan.mockReset();
  plan.mockImplementation(async (_id: string, engine: string) => ({ ok: true, data: engine === "local" ? localPlan : claudePlan }));
});

function panel(onStart = vi.fn()) {
  render(<StartPanel submittalId="doc-sub" starting={false} onStart={onStart} onCancel={vi.fn()} />);
  return onStart;
}

describe("StartPanel", () => {
  it("shows the engine, that text leaves, the cost and the documents that will be sent, then starts with that list", async () => {
    const onStart = panel();
    expect(await screen.findByText("Text leaves this Mac: yes")).toBeInTheDocument();
    expect(plan).toHaveBeenCalledWith("doc-sub", "automatic");
    expect(screen.getByText(/together at most USD 30/)).toBeInTheDocument();
    expect(screen.getByText("These documents will be sent to Claude")).toBeInTheDocument();
    expect(screen.getByText("Pump datasheet rev B.pdf")).toBeInTheDocument();
    expect(screen.getByText(/a contract goes only with the owner's recorded yes/)).toBeInTheDocument();
    expect(screen.getByText(/1 more document\(s\) cited are ones you may not read/)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Automatic" })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Start review" }));
    expect(onStart).toHaveBeenCalledWith("automatic", ["doc_1", "doc_2"]);
  });

  it("says nothing leaves for Local only and starts with an empty list", async () => {
    const onStart = panel();
    await screen.findByText("Text leaves this Mac: yes");
    await userEvent.click(screen.getByRole("radio", { name: "Local only" }));
    expect(await screen.findByText("Text leaves this Mac: no")).toBeInTheDocument();
    expect(screen.getByText("Nothing leaves this Mac.")).toBeInTheDocument();
    expect(screen.getByText(/No cost/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start review" }));
    expect(onStart).toHaveBeenCalledWith("local", []);
  });

  it("fails closed: with no plan, only Local only is offered and no Claude start is possible", async () => {
    plan.mockResolvedValue({ ok: false, error: { message: "boom" } });
    const onStart = panel();
    expect(await screen.findByRole("alert")).toHaveTextContent("Claude is not offered");
    expect(screen.queryByRole("radio", { name: "Claude" })).toBeNull();
    expect(screen.queryByRole("radio", { name: "Automatic" })).toBeNull();
    expect(screen.getByRole("radio", { name: "Local only" })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Start review" }));
    expect(onStart).toHaveBeenCalledWith("local", []);
  });

  it("offers no start when the plan refuses, and when the list could not be worked out", async () => {
    plan.mockResolvedValue({ ok: true, data: { ...claudePlan, refused: "Claude is not available for this paper" } });
    panel();
    expect(await screen.findByText("Claude is not available for this paper")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start review" })).toBeDisabled();
  });

  it("offers no Claude start when the list of documents could not be worked out", async () => {
    plan.mockResolvedValue({ ok: true, data: { ...claudePlan, documents: { leaving: [], not_sent: [], not_readable: 0, unreadable: true, summary: "could not be worked out" } } });
    panel();
    expect(await screen.findByText(/could not be worked out/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start review" })).toBeDisabled();
  });

  it("never names a document the reader may not open", async () => {
    panel();
    await screen.findByText("Text leaves this Mac: yes");
    expect(screen.queryByText(/doc_[0-9]/)).toBeNull();
  });
});
