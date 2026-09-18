import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CommandPalette } from "./CommandPalette";

describe("CommandPalette", () => {
  it("opens with Ctrl+K and keeps administration commands admin-only", () => {
    const onNavigate = vi.fn();
    const connection = { state: "online", health: { ok: true, embed_model_present: true, answer_model_present: true, ingestion: { alive: true, stalled: false, busy: false } }, at: 1 } as const;
    render(<CommandPalette onNavigate={onNavigate} auth={{ required: true, user: { id: "u", email: "a", display_name: "A", roles: [] } }} connection={connection} />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open administration/i })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "guided" } });
    fireEvent.click(screen.getByRole("button", { name: /open guided review/i }));
    expect(onNavigate).toHaveBeenCalledWith("review");
  });
});
