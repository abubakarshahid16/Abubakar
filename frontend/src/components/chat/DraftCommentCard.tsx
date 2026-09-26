/**
 * A drafted review comment, shown for an engineer to read, edit and copy.
 *
 * A DRAFT IS NOT A FINDING. Nothing here writes to a review or a comment
 * sheet; the card says so, and the text stays editable because the engineer,
 * not the model, decides what goes to the contractor.
 */
import { useState } from "react";

import { plainText } from "./AnswerActions";

export function DraftCommentCard({ text }: { text: string }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(() => plainText(text));
  const [copied, setCopied] = useState(false);
  return (
    <section
      aria-label="Draft comment"
      className="mt-2 overflow-hidden rounded-[var(--radius-md)] border border-ink-600 bg-ink-850"
    >
      <header className="flex items-center justify-between gap-2 border-b border-ink-700 px-3.5 py-2.5">
        <div className="flex items-center gap-2">
          <p className="text-sm font-semibold text-slateish-100">Draft comment</p>
          <span className="rounded-[var(--radius-full)] border border-warn-500/40 bg-warn-500/10 px-2 py-0.5 text-xs text-warn-500">
            Needs an engineer
          </span>
        </div>
        <button
          type="button"
          aria-pressed={editing}
          onClick={() => setEditing((e) => !e)}
          className="rounded-[var(--radius-sm)] border border-ink-600 px-2.5 py-1 text-xs text-slateish-200 hover:bg-ink-700"
        >
          {editing ? "Done" : "Edit"}
        </button>
      </header>
      {editing ? (
        <label className="block px-3.5 py-2.5">
          <span className="sr-only">Draft comment text</span>
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={5}
            className="w-full rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-2.5 py-2 text-sm text-slateish-100"
          />
        </label>
      ) : (
        <p className="whitespace-pre-wrap px-3.5 py-2.5 text-[15px] leading-7 text-slateish-200">{value}</p>
      )}
      <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-ink-700 px-3.5 py-2">
        <p className="text-xs text-slateish-500">
          Not added to any review yet. Read it against the sources before it goes to the contractor.
        </p>
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard?.writeText(value).then(
              () => setCopied(true),
              () => setCopied(false),
            );
          }}
          className="rounded-[var(--radius-sm)] border border-ink-600 px-2.5 py-1 text-xs text-slateish-200 hover:bg-ink-700"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </footer>
    </section>
  );
}
