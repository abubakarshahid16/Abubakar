/**
 * G3: a review start that fails is never silent. The error is said in plain words where the start was pressed; the paper's row
 * stays "Not reviewed: the start failed (<reason>)"; a 401 says the sign-in ended and the Sign in screen says why it is there.
 * "Review all" is not drawn while the general review is on. Invented papers only.
 */
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentRecord } from "../../../../types/api";

const startReviewRun = vi.fn();
const planFor = vi.fn();
vi.mock("../../../../api/client", () => ({
  api: {},
  auth: { me: async () => ({ ok: true, data: { required: true, user: { id: "u-1", roles: ["admin"] } } }) },
  classification: {},
  reviews: { readiness: vi.fn(), cancelJob: vi.fn(), reviewRunCounts: vi.fn(), reviewRuns: async () => ({ ok: true, data: { runs: [] } }) },
}));
vi.mock("../../../../api/reviewPlan", () => ({
  reviewPlan: { plan: (...a: unknown[]) => planFor(...a), start: (...a: unknown[]) => startReviewRun(...a) },
}));
vi.mock("../reviewWatch", () => ({ watchRun: vi.fn() }));
vi.mock("../NewReviewDropZone", () => ({ NewReviewDropZone: () => <p data-testid="drop-zone" /> }));

import { LoginView } from "../../../../views/LoginView";
import { REVIEW_EACH_LINE, WorkspaceLanding } from "./WorkspaceLanding";
import { resetStartFailures } from "../startFailures";

const doc = (id: string, filename: string) =>
  ({ id, filename, uploaded_at: "2026-11-18T08:00:00Z", indexed_at: null, document_role: null }) as unknown as DocumentRecord;
const DOCS = [doc("d1", "Invented paper one.pdf"), doc("d2", "Invented paper two.pdf")];

const refused = (code: string, message: string) => ({ ok: false, disconnected: false, error: { code, message } });

function show(over: Partial<Parameters<typeof WorkspaceLanding>[0]> = {}) {
  return render(
    <WorkspaceLanding documents={DOCS} runs={[]} submittalsTotal={2} onOpenRun={vi.fn()} onReload={vi.fn()}
      loadReadyCounts={async () => ({})} isAdmin {...over} />,
  );
}
const rowOf = (name: string) => screen.getAllByTestId("landing-row").find((r) => r.textContent?.includes(name))!;

async function pressStartOn(name: string) {
  const card = screen.getByTestId("new-review-card");
  await userEvent.selectOptions(within(card).getByLabelText("Choose a paper"), DOCS.find((d) => d.filename === name)!.id);
  await userEvent.click(within(card).getByRole("button", { name: "Start review" }));
  await userEvent.click(await within(card).findByRole("button", { name: "Start review" }));
  return card;
}

beforeEach(() => {
  resetStartFailures();
  startReviewRun.mockReset();
  planFor.mockReset().mockResolvedValue({ ok: true, data: { choice: "automatic", parts: [], text_leaves: false, refused: null,
    documents: { leaving: [], not_sent: [], not_readable: 0 } } });
  localStorage.clear();
});
afterEach(() => resetStartFailures());

describe("Review all while the general review is on", () => {
  it("is not drawn: one plain line says each paper is reviewed on its own", () => {
    show({ generalReviewOn: true });
    expect(screen.queryByRole("button", { name: /Review all not reviewed/ })).toBeNull();
    expect(screen.getByTestId("review-each-line")).toHaveTextContent(REVIEW_EACH_LINE);
    expect(REVIEW_EACH_LINE).toBe("Each paper is reviewed on its own with the Review button.");
  });
  it("is unchanged with the earlier engine (prop left out)", () => {
    show();
    expect(screen.getByRole("button", { name: /Review all not reviewed \(2 of the contractor documents listed here\)/ })).toBeInTheDocument();
    expect(screen.queryByTestId("review-each-line")).toBeNull();
  });
});

describe("a start that fails says why and keeps the paper marked", () => {
  it("a 409: the reason is shown at the start and the row says Not reviewed: the start failed (reason)", async () => {
    startReviewRun.mockResolvedValue(refused("conflict", "The general review does not run on Local only. Choose Automatic or Claude."));
    show();
    const card = await pressStartOn("Invented paper one.pdf");
    expect(await within(card).findByRole("alert")).toHaveTextContent("The general review does not run on Local only. Choose Automatic or Claude.");
    expect(rowOf("Invented paper one.pdf")).toHaveTextContent(
      "Not reviewed: the start failed (The general review does not run on Local only. Choose Automatic or Claude)",
    );
    expect(rowOf("Invented paper two.pdf")).not.toHaveTextContent("the start failed");
  });

  it("a refusal with no words still gives a reason", async () => {
    startReviewRun.mockResolvedValue(refused("internal", ""));
    show();
    await pressStartOn("Invented paper one.pdf");
    expect(await screen.findByText(/the server gave no reason/, { selector: "[role=alert]" })).toBeInTheDocument();
    expect(rowOf("Invented paper one.pdf")).toHaveTextContent("Not reviewed: the start failed (the server gave no reason)");
  });

  it("an already-running refusal is not marked as a failed start", async () => {
    startReviewRun.mockResolvedValue(refused("conflict", "A review of this paper is already queued or running (run-9)."));
    show();
    await pressStartOn("Invented paper one.pdf");
    expect(await screen.findByRole("button", { name: "Open the review that is running" })).toBeInTheDocument();
    expect(rowOf("Invented paper one.pdf")).not.toHaveTextContent("the start failed");
  });

  it("a later start that works clears the mark", async () => {
    startReviewRun.mockResolvedValueOnce(refused("conflict", "Not now.")).mockResolvedValueOnce({ ok: true, data: { review_run_id: "run-new", submittal_filename: "Invented paper one.pdf" } });
    show();
    await pressStartOn("Invented paper one.pdf");
    expect(await screen.findByText(/Not reviewed: the start failed \(Not now\)/)).toBeInTheDocument();
    const card = screen.getByTestId("new-review-card");
    await userEvent.click(within(card).getByRole("button", { name: "Start review" }));
    await act(async () => {});
    expect(rowOf("Invented paper one.pdf")).not.toHaveTextContent("the start failed");
  });

  it("a 401: the screen says the sign-in ended, the row is marked, and the Sign in screen says why it is there", async () => {
    startReviewRun.mockResolvedValue(refused("unauthenticated", "You are not signed in, or your session has expired. Sign in to continue."));
    const first = show();
    const card = await pressStartOn("Invented paper one.pdf");
    expect(await within(card).findByRole("alert")).toHaveTextContent("Your sign-in ended; sign in and press Review again");
    expect(rowOf("Invented paper one.pdf")).toHaveTextContent("Not reviewed: the start failed (your sign-in ended)");
    first.unmount();
    render(<LoginView onLogin={async () => ({ ok: true })} connected />);
    expect(screen.getByTestId("sign-in-ended-on-start")).toHaveTextContent("Your sign-in ended; sign in and press Review again");
    await userEvent.type(screen.getByLabelText("Email"), "eng@example.test");
    await userEvent.type(screen.getByLabelText("Password"), "invented-pass");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.queryByTestId("sign-in-ended-on-start")).toBeNull();
  });

  it("the Sign in screen carries no such line when no start ended the sign-in", () => {
    render(<LoginView onLogin={async () => ({ ok: true })} connected />);
    expect(screen.queryByTestId("sign-in-ended-on-start")).toBeNull();
  });
});
