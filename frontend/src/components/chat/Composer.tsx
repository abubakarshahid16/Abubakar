/**
 * Where a question is typed. Enter sends, Shift+Enter starts a new line, and
 * the count appears as the limit comes near - the backend accepts 500
 * characters, and a question cut short silently is a different question.
 *
 * The engine picker lists what the backend says can answer, and why one
 * cannot; it never guesses. "Local model" narrows to this machine only - the
 * backend refuses to widen, so choosing it is a real privacy choice.
 */
import { useEffect, useRef, useState } from "react";

import type { ChatModels } from "../../types/api";
import { DocumentPicker, type PickedDocument } from "./DocumentPicker";

export const MAX_QUESTION = 500;

export type ModelChoice = "claude" | "local";

export function Composer({
  value,
  onChange,
  onSubmit,
  disabled,
  busy,
  hero = false,
  placeholder,
  models,
  model,
  onModelChange,
  onRecords,
  onUpload,
  picked = [],
  onPick,
  pickerOpen = false,
  onPickerOpen,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  /** offline: nothing can be sent */
  disabled?: boolean;
  /** an answer is being written: typing is fine, sending waits */
  busy?: boolean;
  hero?: boolean;
  placeholder: string;
  models: ChatModels | null;
  model: ModelChoice | null;
  onModelChange: (m: ModelChoice) => void;
  onRecords: () => void;
  onUpload?: () => void;
  /** "@ a document": the documents the next answers come from */
  picked?: PickedDocument[];
  onPick?: (next: PickedDocument[]) => void;
  pickerOpen?: boolean;
  onPickerOpen?: (open: boolean) => void;
}) {
  const [menu, setMenu] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const over = value.length > MAX_QUESTION;
  const canSend = !disabled && !busy && value.trim().length > 0 && !over;

  // Grow with the text, to a limit, rather than scrolling a two-line box.
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  }, [value]);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (canSend) onSubmit();
      }}
      className={[
        "rounded-[var(--radius-lg)] border border-ink-600 bg-ink-850 shadow-[var(--shadow-raised)] motion-safe:transition-shadow focus-within:border-signal-500/50 focus-within:shadow-[var(--shadow-glow)]",
        hero ? "px-4 pb-3 pt-4" : "px-3.5 pb-2.5 pt-3",
      ].join(" ")}
    >
      {picked.length > 0 && (
        <ul aria-label="Answering from" className="mb-2 flex flex-wrap gap-1.5">
          {picked.map((d) => (
            <li
              key={d.id}
              className="inline-flex items-center gap-1 rounded-[var(--radius-full)] border border-signal-500/40 bg-signal-500/10 px-2 py-0.5 text-xs text-signal-300"
            >
              @{d.name}
              {onPick && (
                <button
                  type="button"
                  aria-label={`Stop answering from ${d.name}`}
                  onClick={() => onPick(picked.filter((p) => p.id !== d.id))}
                  className="min-h-0 px-0.5 text-slateish-400 hover:text-slateish-100"
                >
                  ×
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <label htmlFor="chat-question" className="sr-only">
        Your question
      </label>
      <textarea
        id="chat-question"
        ref={area}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            if (canSend) onSubmit();
          }
        }}
        disabled={disabled}
        rows={hero ? 2 : 1}
        placeholder={placeholder}
        aria-describedby="chat-question-count"
        className="block w-full resize-none bg-transparent text-[15px] leading-6 text-slateish-100 outline-none placeholder:text-slateish-500 disabled:opacity-50"
      />
      <div className="mt-2 flex items-center justify-between gap-2">
        <div className="relative flex items-center gap-2">
          <button
            type="button"
            aria-label="More options"
            aria-expanded={menu}
            aria-haspopup="true"
            onClick={() => setMenu((m) => !m)}
            className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-full)] border border-ink-600 text-slateish-300 hover:border-signal-500/50 hover:bg-ink-800"
          >
            +
          </button>
          {onPick && onPickerOpen && (
            <button
              type="button"
              aria-expanded={pickerOpen}
              aria-haspopup="dialog"
              onClick={() => onPickerOpen(!pickerOpen)}
              className={[
                "rounded-[var(--radius-full)] border px-3 py-1 text-xs motion-safe:transition-colors",
                picked.length > 0
                  ? "border-signal-500/60 text-signal-300"
                  : "border-ink-600 text-slateish-300 hover:border-signal-500/50 hover:bg-ink-800",
              ].join(" ")}
            >
              @ a document{picked.length > 0 ? ` (${picked.length})` : ""}
            </button>
          )}
          {pickerOpen && onPick && onPickerOpen && (
            <DocumentPicker picked={picked} onChange={onPick} onClose={() => onPickerOpen(false)} />
          )}
          {menu && (
            <div
              role="group"
              aria-label="More options"
              className="absolute bottom-10 left-0 z-30 w-60 rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-1 shadow-[var(--shadow-floating)]"
            >
              <button
                type="button"
                onClick={() => {
                  setMenu(false);
                  onRecords();
                }}
                className="block w-full rounded-[var(--radius-sm)] px-3 py-2 text-left text-sm text-slateish-200 hover:bg-ink-700"
              >
                Search workflow records
                <span className="block text-xs text-slateish-500">Deliverables, findings, risks</span>
              </button>
              {onUpload && (
                <button
                  type="button"
                  onClick={() => {
                    setMenu(false);
                    onUpload();
                  }}
                  className="block w-full rounded-[var(--radius-sm)] px-3 py-2 text-left text-sm text-slateish-200 hover:bg-ink-700"
                >
                  Add a document
                  <span className="block text-xs text-slateish-500">Opens the Documents screen</span>
                </button>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span
            id="chat-question-count"
            aria-live="polite"
            className={[
              "font-mono text-xs",
              over ? "text-danger-500" : "text-slateish-500",
              value.length >= MAX_QUESTION * 0.8 ? "" : "sr-only",
            ].join(" ")}
          >
            {value.length}/{MAX_QUESTION}
            {over ? " - too long to send" : ""}
          </span>
          {models && model && (
            <label className="flex items-center gap-1 rounded-[var(--radius-full)] border border-ink-600 px-2.5 py-1 text-xs text-slateish-300">
              <span>Model:</span>
              <select
                aria-label="Model"
                value={model}
                onChange={(e) => onModelChange(e.target.value as ModelChoice)}
                className="bg-transparent text-slateish-200 outline-none"
              >
                {models.models.map((m) => (
                  <option key={m.id} value={m.id} disabled={!m.available} title={m.reason ?? undefined}>
                    {m.label}
                    {m.available ? "" : " (unavailable)"}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button
            type="submit"
            aria-label="Ask"
            disabled={!canSend}
            className="flex h-9 w-9 items-center justify-center rounded-[var(--radius-full)] bg-signal-500 text-lg font-semibold text-ink-950 shadow-[var(--shadow-raised)] motion-safe:transition-transform hover:bg-signal-400 active:scale-[0.96] disabled:bg-signal-500/20 disabled:text-signal-300 disabled:shadow-none"
          >
            <span aria-hidden>↑</span>
          </button>
        </div>
      </div>
    </form>
  );
}
