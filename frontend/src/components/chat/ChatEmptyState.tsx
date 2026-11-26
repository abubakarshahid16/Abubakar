/**
 * The first thing a reader sees: one question, one box, and a few ways in.
 *
 * The suggestion cards are fixed, general examples of the kinds of question
 * the chat answers - they name no document, because a card that promises an
 * answer about a file that is not loaded is a card that fails when pressed.
 * "Continue" links are the reader's own most recent conversations.
 */
import type { ConversationSummary } from "../../types/api";
import { Button } from "../kit/Kit";

export const STARTERS: readonly { ask: string; kind: string }[] = [
  { ask: "Does my latest submittal meet the standards it references?", kind: "Submittal check" },
  { ask: "Which standards apply to this datasheet?", kind: "Standards check" },
  { ask: "Summarise the hydrotest requirements in plain English", kind: "Understand a standard" },
  { ask: "What is the difference between barg and bara?", kind: "General question" },
];

export function ChatEmptyHeading() {
  // the page title is the menu's name (owner, 26 Nov 2026: title = menu name); the question stays as the big line under it
  return <>
    <h1 className="mb-1 text-center text-sm font-semibold text-slateish-400">Chat</h1>
    <p className="mb-6 text-center font-serif text-3xl text-slateish-100">What can I help with?</p>
  </>;
}

/** The ways in, under the box: starter questions and "Continue:". */
export function ChatStarters({
  onAsk,
  recent,
  onOpen,
  disabled,
}: {
  onAsk: (text: string) => void;
  recent: ConversationSummary[];
  onOpen: (id: string) => void;
  disabled?: boolean;
}) {
  return (
    <div>
      <div className="mt-5 grid gap-2.5 sm:grid-cols-2">
        {STARTERS.map((s) => (
          <Button variant="secondary"
            key={s.ask}
           
            disabled={disabled}
            onClick={() => onAsk(s.ask)}
          >
            <span className="block text-sm text-slateish-100">{s.ask}</span>
            <span className="mt-0.5 block text-xs text-slateish-500">{s.kind}</span>
          </Button>
        ))}
      </div>
      {recent.length > 0 && (
        <nav aria-label="Recent conversations" className="mt-5 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-xs text-slateish-500">
          <span>Continue:</span>
          {recent.slice(0, 3).map((c) => (
            <Button variant="secondary"
              key={c.id}
             
              aria-label={`Continue ${c.title}`}
              onClick={() => onOpen(c.id)}
              title={c.title}
            >
              {c.title}
            </Button>
          ))}
        </nav>
      )}
    </div>
  );
}

