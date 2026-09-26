/**
 * The first thing a reader sees: one question, one box, and a few ways in.
 *
 * The suggestion cards are fixed, general examples of the kinds of question
 * the chat answers - they name no document, because a card that promises an
 * answer about a file that is not loaded is a card that fails when pressed.
 * "Continue" links are the reader's own most recent conversations.
 */
import type { ConversationSummary } from "../../types/api";

export const STARTERS: readonly { ask: string; kind: string }[] = [
  { ask: "Does my latest submittal meet the standards it references?", kind: "Submittal check" },
  { ask: "Which standards apply to this datasheet?", kind: "Standards check" },
  { ask: "Summarise the hydrotest requirements in plain English", kind: "Understand a standard" },
  { ask: "What is the difference between barg and bara?", kind: "General question" },
];

export function ChatEmptyHeading() {
  return <h1 className="mb-6 text-center font-serif text-3xl text-slateish-100">What can I help with?</h1>;
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
          <button
            key={s.ask}
            type="button"
            disabled={disabled}
            onClick={() => onAsk(s.ask)}
            className="rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 px-4 py-3 text-left motion-safe:transition-colors hover:border-signal-500/40 hover:bg-ink-800 disabled:opacity-50"
          >
            <span className="block text-sm text-slateish-100">{s.ask}</span>
            <span className="mt-0.5 block text-xs text-slateish-500">{s.kind}</span>
          </button>
        ))}
      </div>
      {recent.length > 0 && (
        <p className="mt-5 text-center text-xs text-slateish-500">
          Continue:{" "}
          {recent.slice(0, 3).map((c, i) => (
            <span key={c.id}>
              {i > 0 && " · "}
              <button
                type="button"
                aria-label={`Continue ${c.title}`}
                onClick={() => onOpen(c.id)}
                className="min-h-0 text-signal-400 underline decoration-signal-500/40 underline-offset-2 hover:text-signal-300"
              >
                {c.title}
              </button>
            </span>
          ))}
        </p>
      )}
    </div>
  );
}
