/**
 * Drawer focus behaviour.
 *
 * THREE PROPERTIES a keyboard reader depends on:
 *   - Focus moves into the panel ONCE, on open, and is NOT pulled back when
 *     the parent re-renders with a new inline `onClose` (the Documents page
 *     does exactly that on every poll).
 *   - Closing returns focus to the control that opened it.
 *   - Tab cannot leave the panel (`aria-modal` promises the page is inert).
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";

import { Drawer } from "./Drawer";

afterEach(cleanup);

function Host() {
  const [open, setOpen] = useState(false);
  const [, setTick] = useState(0);
  return (
    <div>
      <button onClick={() => setOpen(true)}>Open STD-A-001</button>
      <button onClick={() => setTick((n) => n + 1)}>Rerender</button>
      {open && (
        <Drawer title="Details - STD-A-001.pdf" onClose={() => setOpen(false)}>
          <input aria-label="Title" />
        </Drawer>
      )}
    </div>
  );
}

it("moves focus into the panel when it opens", () => {
  render(<Host />);
  fireEvent.click(screen.getByText("Open STD-A-001"));
  expect(screen.getByRole("dialog")).toHaveFocus();
});

it("does not steal focus back when the parent re-renders", () => {
  render(<Host />);
  fireEvent.click(screen.getByText("Open STD-A-001"));
  const input = screen.getByLabelText("Title");
  input.focus();
  // A new inline onClose arrives with every parent render.
  fireEvent.click(screen.getByText("Rerender"));
  expect(input).toHaveFocus();
});

it("returns focus to the opener on close, and Escape closes", () => {
  render(<Host />);
  const opener = screen.getByText("Open STD-A-001");
  opener.focus();
  fireEvent.click(opener);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(opener).toHaveFocus();
});

it("calls the latest onClose on Escape", () => {
  const first = vi.fn();
  const second = vi.fn();
  const { rerender } = render(<Drawer title="t" onClose={first}>x</Drawer>);
  rerender(<Drawer title="t" onClose={second}>x</Drawer>);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(first).not.toHaveBeenCalled();
  expect(second).toHaveBeenCalledTimes(1);
});

it("keeps Tab and Shift+Tab inside the panel", () => {
  render(<Host />);
  fireEvent.click(screen.getByText("Open STD-A-001"));
  const close = screen.getByRole("button", { name: "Close" });
  const input = screen.getByLabelText("Title");
  // Order in the panel: Close, then the input (last).
  input.focus();
  fireEvent.keyDown(document, { key: "Tab" });
  expect(close).toHaveFocus();
  fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
  expect(input).toHaveFocus();
});
