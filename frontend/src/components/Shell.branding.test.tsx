/**
 * The sidebar is the first thing a non-engineer reads, so its wording is
 * behaviour, not decoration.
 *
 * Two rules are under test:
 *
 *  - No internal jargon. "Sunday POC lane", the codename "Nabaa" and the claim
 *    "FEED intelligence" all meant something to the team and nothing to a
 *    reader; "FEED" was additionally FALSE, because this corpus is design
 *    guides, security standards and a coatings spec, with no FEED document in
 *    it. A name the product does not deserve is a defect like any other.
 *
 *  - The footer's honesty statements survive the rewording. The LABELS were
 *    made plainer; the VALUES carry the admissions - that the market figures
 *    are a sample and not live data, and that a report is frozen evidence
 *    rather than a live view - and those must not be softened by a later edit
 *    that is only trying to make the sidebar read more smoothly.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Shell, type Connection } from "./Shell";

const connecting: Connection = { state: "connecting" };

function renderShell() {
  render(
    <Shell
      view="documents"
      onNavigate={() => {}}
      connection={connecting}
      theme="light"
      onThemeChange={() => {}}
    >
      <p>body</p>
    </Shell>,
  );
  // Everything asserted below lives in the sidebar specifically, not merely
  // "somewhere on the page" - scoping is what makes the absence checks mean
  // anything.
  return within(screen.getByRole("navigation", { name: "Main" }));
}

describe("sidebar wording", () => {
  it("carries no internal jargon, codename or FEED claim", () => {
    const sidebar = renderShell();

    expect(sidebar.queryByText(/POC lane/i)).toBeNull();
    expect(sidebar.queryByText(/Nabaa/i)).toBeNull();
    expect(sidebar.queryByText(/FEED/i)).toBeNull();
    // Belt and braces: the strings must be absent from the sidebar's text as a
    // whole, not just from any single element a query happens to match.
    const text = screen.getByRole("navigation", { name: "Main" }).textContent ?? "";
    expect(text).not.toMatch(/POC lane/i);
    expect(text).not.toMatch(/Nabaa/i);
    expect(text).not.toMatch(/FEED/i);
  });

  it("names the product", () => {
    const sidebar = renderShell();
    expect(sidebar.getByText("RAG Intelligence System")).toBeInTheDocument();
  });

  it("still admits the market figures are a sample and reports are frozen", () => {
    const sidebar = renderShell();

    // "sample only" is the whole point of the row: it says these numbers are
    // illustrative. A label reworded to "Market data" is fine; a value
    // reworded to anything that implies live coverage is not.
    expect(sidebar.getByText(/sample only/i)).toBeInTheDocument();
    // A report is a frozen PDF: evidence as it stood, not a live view.
    expect(sidebar.getByText(/frozen PDF/i)).toBeInTheDocument();
  });
});
