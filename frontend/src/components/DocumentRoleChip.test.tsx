/** Order 14 lane E: the suggested role chip. Off: nothing at all. On: "suggested, confirm or change"; a suggestion is never a role. */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentClassification } from "../types/api";

let enabled = false;
const setRoleBulk = vi.fn();
vi.mock("../api/roleSuggestion", async (orig) => ({
  ...(await orig<typeof import("../api/roleSuggestion")>()),
  roleSuggestionSwitch: () => Promise.resolve({ enabled, review_roles: [] }),
}));
vi.mock("../api/documents", () => ({ classification: { setRoleBulk: (...a: unknown[]) => setRoleBulk(...a) } }));

import { DocumentRoleChip } from "./DocumentRoleChip";

const base = { document_id: "doc-1", document_role: null, document_kind: "contract", document_kind_state: "suggested" } as unknown as DocumentClassification;
const withSuggestion = (s: object) =>
  ({ ...base, document_kind_evidence: { role_suggestion: s } }) as unknown as DocumentClassification;

beforeEach(() => {
  enabled = false;
  setRoleBulk.mockReset();
  setRoleBulk.mockResolvedValue({ ok: true, data: { failed: [] } });
});
afterEach(() => vi.clearAllMocks());

describe("DocumentRoleChip", () => {
  it("renders nothing at all when the switch is off", async () => {
    const { container } = render(<DocumentRoleChip classification={withSuggestion({ role: "CONTRACT_DOCUMENT", basis: "kind", kind: "contract" })} isAdmin />);
    await new Promise((r) => setTimeout(r, 0));
    expect(container.innerHTML).toBe("");
  });

  it("shows the suggestion as suggested, confirm or change, with the disagreement named", async () => {
    enabled = true;
    render(<DocumentRoleChip classification={withSuggestion({ role: "CONTRACTOR_SUBMITTAL", basis: "page", page: "review", kind: "contract", kind_says: "CONTRACT_DOCUMENT" })} isAdmin />);
    expect(await screen.findByTestId("role-suggestion")).toHaveTextContent(
      "Suggested role: contractor submittal (it was uploaded on the AI Submittal Review page; its contents read as a contract document). Suggested, confirm or change.",
    );
    expect(screen.getByRole("button", { name: "Confirm role" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change role" })).toBeInTheDocument();
  });

  it("writes a role only when an administrator confirms, through the existing role write", async () => {
    enabled = true;
    render(<DocumentRoleChip classification={withSuggestion({ role: "CONTRACT_DOCUMENT", basis: "kind", kind: "contract" })} isAdmin />);
    await userEvent.click(await screen.findByRole("button", { name: "Confirm role" }));
    expect(setRoleBulk).toHaveBeenCalledWith({ document_ids: ["doc-1"], document_role: "CONTRACT_DOCUMENT" });
    expect(await screen.findByTestId("role-suggestion-done")).toHaveTextContent("Role set: contract document");
  });

  it("shows no buttons to a non-administrator and nothing for a document that has a role", async () => {
    enabled = true;
    const { rerender } = render(<DocumentRoleChip classification={withSuggestion({ role: "CONTRACT_DOCUMENT", basis: "kind" })} />);
    await screen.findByTestId("role-suggestion");
    expect(screen.queryByRole("button")).toBeNull();
    rerender(<DocumentRoleChip classification={{ ...withSuggestion({ role: "CONTRACT_DOCUMENT", basis: "kind" }), document_role: "COMPANY_STANDARD" } as DocumentClassification} isAdmin />);
    await waitFor(() => expect(screen.queryByTestId("role-suggestion")).toBeNull());
    expect(setRoleBulk).not.toHaveBeenCalled();
  });
});
