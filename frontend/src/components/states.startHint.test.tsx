import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DisconnectedState } from "./states";

describe("DisconnectedState start hint", () => {
  it("is machine-neutral: python run.py, no drive, no backslash path, no old name", () => {
    render(<DisconnectedState />);
    const box = screen.getByRole("alert");
    const text = box.textContent ?? "";
    expect(text).toContain("python run.py");
    expect(text).not.toMatch(/[A-Za-z]:\\/);
    expect(text).not.toContain("\\");
    expect(text.toLowerCase()).not.toContain("rag_chatbot");
  });
});
