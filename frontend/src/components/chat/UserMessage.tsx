/**
 * The reader's own turn: their words, right-aligned, with Edit - which puts
 * the words back in the box to be changed and asked again as a new turn (the
 * old answer stays where it was; nothing is rewritten behind their back).
 *
 * When a follow-up was read with terms carried in from earlier questions,
 * that is said under the bubble. The question is never silently rewritten.
 */
import type { Message } from "../../types/api";
import { Button } from "../kit/Kit";

export function UserMessage({
  message,
  onEdit,
}: {
  message: Pick<Message, "text" | "carried_terms">;
  onEdit?: (text: string) => void;
}) {
  // `?? []`: carried_terms was added later, and one legacy row must not take
  // the whole transcript down with it.
  const carried = message.carried_terms ?? [];
  return (
    <div className="group flex flex-col items-end">
      <div className="flex max-w-[85%] items-center gap-2">
        {onEdit && message.text && (
          <Button variant="secondary" size="sm"
           
            onClick={() => onEdit(message.text ?? "")}
          >
            Edit
          </Button>
        )}
        <p className="whitespace-pre-wrap rounded-[var(--radius-lg)] bg-ink-700 px-4 py-2.5 text-[15px] leading-6 text-slateish-100 shadow-[var(--shadow-resting)]">
          {message.text}
        </p>
      </div>
      {carried.length > 0 && (
        <p className="mt-1 max-w-[85%] text-right text-xs text-slateish-500">
          Read as a follow-up. Also searched for{" "}
          {carried.map((t, i) => (
            <span key={t}>
              {i > 0 && ", "}
              <span className="font-mono text-slateish-400">{t}</span>
            </span>
          ))}
          .
        </p>
      )}
    </div>
  );
}
