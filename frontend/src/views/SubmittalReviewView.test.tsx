import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SubmittalReviewView } from "./SubmittalReviewView";

describe("SubmittalReviewView", () => {
  it("shows visible progress, allows revisiting, and opens the existing screens", () => {
    const onNavigate = vi.fn();
    render(<SubmittalReviewView onNavigate={onNavigate} />);
    expect(screen.getByRole("heading", { name: "Guided submittal review" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /mark step complete/i }));
    expect(screen.getByRole("heading", { name: "Run engineering review" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /select submittal/i }));
    expect(screen.getByRole("heading", { name: "Select submittal" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /open documents/i }));
    expect(onNavigate).toHaveBeenCalledWith("documents");
  });
});
