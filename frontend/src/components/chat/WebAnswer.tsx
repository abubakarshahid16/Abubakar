/**
 * The chat's web lane, on screen: the consent card, and the answer citing
 * the web as the web.
 *
 * ASK FIRST. The consent card shows the one phrase that would leave and sends
 * nothing; "Search once" is the only control that does. The phrase shown is
 * the server's - built from the reader's words through the whitelist - and
 * pressing the button sends no text at all: the server rebuilds it.
 *
 * WEB SOURCES ARE NOT DOCUMENTS. They open the site in a new tab, carry their
 * site and date, and are marked unverified. They never become a document
 * chip, a page preview or a finding.
 */
import { useState } from "react";

import type { ChatSource, Message } from "../../types/api";
import { Markdown } from "./Markdown";

export function WebConsent({
  message,
  onSearch,
}: {
  message: Message;
  onSearch?: () => Promise<{ ok: true } | { ok: false; message: string }>;
}) {
  const payload = message.payload ?? {};
  const phrase = payload.web_phrase ?? null;
  const offerable = Boolean(phrase && payload.web_available && !payload.web_searched && onSearch);
  const [state, setState] = useState<"offer" | "searching" | "cancelled" | "failed">("offer");
  const [failure, setFailure] = useState<string | null>(null);

  const search = async () => {
    if (!onSearch) return;
    setState("searching");
    const r = await onSearch();
    if (r.ok) return; // the answer arrives as the next turn
    setFailure(r.message);
    setState("failed");
  };

  return (
    <div>
      <Markdown text={message.text ?? ""} />
      {offerable && (state === "offer" || state === "searching" || state === "failed") && (
        <div
          role="group"
          aria-label="Web search"
          className="mt-2 rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 px-3.5 py-2.5"
        >
          <p className="text-xs text-slateish-400">
            Would send: <span className="font-mono text-slateish-100">"{phrase}"</span>
          </p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => void search()}
              disabled={state === "searching"}
              className="rounded-[var(--radius-sm)] bg-signal-500 px-3 py-1.5 text-sm font-semibold text-ink-950 hover:bg-signal-400 disabled:opacity-50"
            >
              {state === "searching" ? "Searching…" : "Search once"}
            </button>
            <button
              type="button"
              onClick={() => setState("cancelled")}
              disabled={state === "searching"}
              className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1.5 text-sm text-slateish-200 hover:bg-ink-700"
            >
              Cancel
            </button>
          </div>
          {failure && (
            <p role="alert" className="mt-2 text-xs text-danger-500">
              {failure}
            </p>
          )}
        </div>
      )}
      {state === "cancelled" && (
        <p role="status" className="mt-2 text-xs text-slateish-500">
          Not searched. Nothing was sent.
        </p>
      )}
      {payload.web_searched && (
        <p className="mt-2 text-xs text-slateish-500">This search has been run; its results are below.</p>
      )}
    </div>
  );
}

export function WebSources({ sources }: { sources: ChatSource[] }) {
  const web = sources.filter((s) => s.kind === "web" && s.url);
  if (web.length === 0) return null;
  return (
    <ul aria-label="Web sources" className="mt-3 space-y-1.5">
      {web.map((s) => (
        <li key={s.n} className="flex flex-wrap items-baseline gap-x-2 text-xs">
          <span className="font-mono font-semibold text-slateish-400">{s.n}</span>
          <a
            href={s.url!}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="min-h-0 text-signal-400 underline decoration-signal-500/40 underline-offset-2 hover:text-signal-300"
          >
            {s.display_name}
          </a>
          {s.clause && <span className="text-slateish-500">{s.clause}</span>}
          <span className="rounded-[var(--radius-full)] border border-warn-500/40 px-1.5 text-warn-500">
            web · unverified
          </span>
        </li>
      ))}
    </ul>
  );
}
