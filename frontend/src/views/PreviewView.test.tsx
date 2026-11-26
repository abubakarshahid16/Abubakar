import { readFileSync } from "node:fs";
import path from "node:path";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { STATUS_WORDS, StatusChip } from "../components/ui";
import { parseRoute } from "../routing";
import { PreviewView } from "./PreviewView";

describe("the new look's preview (owner, 26 Nov 2026, G9)", () => {
  it("shows the three journeys with invented data, and says so", () => {
    const go = vi.fn();
    const { rerender } = render(<PreviewView onNavigate={go} />);
    expect(screen.getByTestId("preview-banner").textContent).toMatch(/invented data\. Nothing on this page is real/);
    expect(screen.getByText("What do you want to do?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "2. Review a document" }));
    expect(go).toHaveBeenCalledWith("preview", "review");
    rerender(<PreviewView journey="review" onNavigate={go} />);
    expect(screen.getByTestId("preview-verdict").textContent).toContain("3 comments need your decision");
    rerender(<PreviewView journey="query" onNavigate={go} />);
    expect(screen.getByTestId("preview-draft").textContent).toContain("Rough draft");
    expect(screen.getByTestId("preview-draft").textContent).toContain("AI, to be checked");
  });

  it("has its own address, out of the menu", () => {
    expect(parseRoute("/preview")).toEqual({ kind: "view", view: "preview", recordId: undefined });
    expect(parseRoute("/preview/query")).toEqual({ kind: "view", view: "preview", recordId: "query" });
  });

  it("names no real client or document: every name on it says it is invented", () => {
    const source = readFileSync(path.resolve(__dirname, "PreviewView.tsx"), "utf8");
    const titles = source.match(/<PageHeader\s+title="[^"]+"/g) ?? [];
    expect(titles.length).toBe(2);
    for (const title of titles) expect(title).toMatch(/\(invented\)/);
  });
});

describe("the status chips keep the honest labels word for word", () => {
  it("says AI, to be checked / Rough draft / Signed / Waiting / Failed", () => {
    expect(Object.values(STATUS_WORDS)).toEqual(["AI, to be checked", "Rough draft", "Signed", "Waiting", "Failed"]);
    render(<StatusChip status="ai" />);
    expect(screen.getByText("AI, to be checked")).toHaveAttribute("data-status", "ai");
  });
});

describe("the look switch", () => {
  it("is off unless VITE_UI_NEW_LOOK is true, and the tokens apply only under data-look=new", () => {
    const app = readFileSync(path.resolve(__dirname, "../App.tsx"), "utf8");
    expect(app).toMatch(/import\.meta\.env\.VITE_UI_NEW_LOOK === "true"/);
    const look = readFileSync(path.resolve(__dirname, "../look.css"), "utf8");
    const opening = look.split("\n").filter((line) => line.trimEnd().endsWith("{"));
    expect(opening.length).toBe(3);
    for (const line of opening) expect(line).toMatch(/^:root\[data-look="new"\]/);
  });
});
