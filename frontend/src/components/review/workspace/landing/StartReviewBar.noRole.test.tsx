/** G2: a paper with no role recorded is listed, with one plain line; a paper with a role carries no such line; nothing sets a role. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DocumentRecord } from "../../../../types/api";
import { NO_ROLE_LINE, landingRowsOf } from "./landingRows";
import { LandingDocumentRow } from "./LandingDocumentRow";
import { StartReviewBar } from "./StartReviewBar";

vi.mock("../ReviewAgainButton", () => ({ ReviewAgainButton: () => <button type="button">Start review</button> }));

const doc = (id: string, role: string | null): DocumentRecord =>
  ({ id, filename: `${id}.pdf`, document_role: role, uploaded_at: "2026-11-18T08:00:00Z", indexed_at: null }) as unknown as DocumentRecord;

describe("a paper with no role recorded", () => {
  it("is offered in the list and says how it will be reviewed once chosen", async () => {
    render(<StartReviewBar documents={[doc("a", null), doc("b", "CONTRACTOR_SUBMITTAL")]} submittalsTotal={2} runs={[]} onStarted={vi.fn()} />);
    expect(screen.queryByTestId("start-no-role")).toBeNull();
    // the bar lists every paper that is not a rule book (G2), so it says "paper", never "submittal"
    const select = screen.getByLabelText("Choose a paper");
    expect(screen.queryByText(/submittal/i)).toBeNull();
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose one of 2", "a.pdf", "b.pdf"]);
    await userEvent.selectOptions(select, "a");
    expect(screen.getByTestId("start-no-role")).toHaveTextContent(NO_ROLE_LINE);
    await userEvent.selectOptions(select, "b");
    expect(screen.queryByTestId("start-no-role")).toBeNull();
  });

  it("carries the line on its row only when no role is recorded", () => {
    const rows = landingRowsOf([doc("a", null), doc("b", "SPECIFICATION")], []);
    const draw = (id: string) => {
      const row = rows.find((r) => r.documentId === id)!;
      return render(<LandingDocumentRow row={row} counts={null} allRuns={[]} mayStart onOpenRun={vi.fn()} onChanged={vi.fn()} />);
    };
    const first = draw("a");
    expect(screen.getByTestId("row-no-role")).toHaveTextContent(NO_ROLE_LINE);
    first.unmount();
    draw("b");
    expect(screen.queryByTestId("row-no-role")).toBeNull();
  });
});
