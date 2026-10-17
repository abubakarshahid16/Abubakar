import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatStarters } from "./ChatEmptyState";

describe("chat starter layout", () => {
  it("keeps long recent conversation names available without widening the chat", () => {
    const onOpen = vi.fn();
    const title = "Review of contractor submittals and all referenced engineering specifications";
    render(
      <ChatStarters
        onAsk={vi.fn()}
        recent={[{
          id: "conversation-1",
          title,
          document_id: null,
          message_count: 2,
          created_at: "2026-10-16T00:00:00Z",
          updated_at: "2026-10-16T00:00:00Z",
          first_question: title,
        }]}
        onOpen={onOpen}
      />,
    );

    const recent = screen.getByRole("button", { name: `Continue ${title}` });
    expect(recent).toHaveAttribute("title", title);
    fireEvent.click(recent);
    expect(onOpen).toHaveBeenCalledWith("conversation-1");
  });
});

