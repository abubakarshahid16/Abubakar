/** The shared kit's parts: one title, two buttons, chips by word, card, table, fields, notices and tiles. Invented values only. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { KIT_WORDS, toneOfWord } from "./chipWords";
import { Button, ButtonLink, Card, LinkButton, Notice, PageHeader, SelectField, StatusChip, Table, TextField, Tile } from "./Kit";
import { KitPreview } from "./KitPreview";

describe("the shared kit", () => {
  it("gives every page the same header: one h1 with the kit's title class", () => {
    render(<PageHeader title="Documents" lead="Every paper you hold." actions={<Button>Upload</Button>} />);
    const h1 = screen.getByRole("heading", { level: 1, name: "Documents" });
    expect(h1.className).toBe("kit-title");
    expect(screen.getByText("Every paper you hold.").className).toBe("kit-lead");
  });
  it("has exactly two button looks, and takes no class from a page", () => {
    render(<><Button variant="primary">A</Button><Button>B</Button><Button size="sm">C</Button><ButtonLink href="#x">D</ButtonLink></>);
    expect(screen.getByRole("button", { name: "A" }).className).toBe("kit-btn kit-btn--primary");
    expect(screen.getByRole("button", { name: "B" }).className).toBe("kit-btn kit-btn--secondary");
    expect(screen.getByRole("button", { name: "C" }).className).toBe("kit-btn kit-btn--secondary kit-btn--sm");
    expect(screen.getByRole("link", { name: "D" }).className).toBe("kit-btn kit-btn--secondary");
    // @ts-expect-error a page cannot give the kit a look of its own
    render(<Button className="bg-signal-500">E</Button>);
  });
  it("colours a chip by its word, the same word the same colour everywhere", () => {
    render(<><StatusChip word="Waiting for approval" /><StatusChip word="In progress" /><StatusChip word="approved" /><StatusChip word="Something new" /></>);
    expect(screen.getByText("Waiting for approval").className).toBe("kit-chip kit-chip--check");
    expect(screen.getByText("In progress").className).toBe("kit-chip kit-chip--info");
    expect(screen.getByText("approved").className).toBe("kit-chip kit-chip--done");
    expect(screen.getByText("Something new").className).toBe("kit-chip kit-chip--plain");
  });
  it("puts a chip's full sentence in its own text for a screen reader", () => {
    render(<StatusChip word="No contractor" why="No contractor yet: add its code once." />);
    const chip = screen.getByTitle("No contractor yet: add its code once.");
    expect(chip.textContent).toBe("No contractor: No contractor yet: add its code once.");
  });
  it("lists each status word once, in one colour", () => {
    const all = Object.values(KIT_WORDS).flat();
    expect(new Set(all).size).toBe(all.length);
    expect(toneOfWord("  Mailbox   problem ")).toBe("late");
  });
  it("draws a table inside its own scrolling box, and fields with their labels", () => {
    render(<><Table caption="Rows" columns={["A", "B"]} rows={[{ key: "1", cells: ["x", "y"] }]} /><TextField id="f1" label="Contractor" hint="Saved here." /><SelectField id="f2" label="Order"><option>Newest</option></SelectField></>);
    expect(screen.getByRole("table").parentElement?.className).toBe("kit-table-wrap");
    expect(screen.getByLabelText("Contractor").className).toBe("kit-input");
    expect(screen.getByLabelText("Order").className).toBe("kit-select");
  });
  it("draws one card, its title a section heading", () => {
    render(<Card title="Who handles it" labelledBy="c1"><p>x</p></Card>);
    const card = screen.getByRole("region", { name: "Who handles it" });
    expect(card.className).toBe("kit-card");
    expect(screen.getByRole("heading", { level: 2, name: "Who handles it" }).className).toBe("kit-section-title");
  });
  it("says a problem notice as an alert and the others as notes", () => {
    render(<><Notice tone="problem">Broken</Notice><Notice>Fact</Notice></>);
    expect(screen.getByRole("alert").textContent).toBe("Broken");
    expect(screen.getByRole("note").textContent).toBe("Fact");
  });
  it("makes the whole tile one button; late in red only above 0, otherwise its words", () => {
    const open = vi.fn();
    render(<><Tile name="Document reviews" number={16} label="waiting for you" done={12} late={0} lateWords="no due dates set" onOpen={open} /><Tile name="Queries" number={3} label="waiting for you" late={2} onOpen={open} /></>);
    const tile = screen.getByRole("button", { name: /Document reviews/ });
    expect(tile.textContent).toBe("Document reviews 16 waiting for you 12 done no due dates set"); // real spaces between the parts
    fireEvent.click(tile);
    expect(open).toHaveBeenCalled();
    expect(screen.getByText("2 late").className).toBe("kit-late");
  });
  it("renders the preview with every part", () => {
    render(<KitPreview />);
    expect(screen.getByRole("heading", { level: 1, name: "Shared kit" })).toBeTruthy();
    expect(screen.getAllByRole("button").length).toBeGreaterThan(8);
  });
  it("keeps a link a link: the link looks the pages had (tone, size, weight), never a boxed button", () => {
    render(<><LinkButton tone="action" size="xs" weight="semibold" onClick={() => undefined}>All reviews of this file (2)</LinkButton><LinkButton onClick={() => undefined}>show all</LinkButton></>);
    expect(screen.getByRole("button", { name: "All reviews of this file (2)" }).className).toBe("kit-link kit-link--action kit-link--xs kit-link--semibold");
    expect(screen.getByRole("button", { name: "show all" }).className).toBe("kit-link"); // no tone: the quiet underlined word
  });
});
