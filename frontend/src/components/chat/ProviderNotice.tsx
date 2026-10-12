/**
 * Audit 101: the reader chose Claude and the LOCAL model answered. A calm
 * note, not an error: the answer is valid and still shows its sources, the
 * reader just needs to know which engine wrote it. Rendered only when the
 * answer says BOTH that Claude was requested and that the local engine
 * answered; a turn stored before the keys existed has neither, so it renders
 * exactly as it always did.
 */
export function providerNoteFor(v: {
  requested_provider?: string | null;
  provider?: string | null;
  provider_note?: string | null;
}): string | null {
  const note = (v.provider_note ?? "").trim();
  return v.requested_provider === "claude" && v.provider === "ollama" && note ? note : null;
}

export function ProviderNotice({ note }: { note: string | null }) {
  if (!note) return null;
  return (
    <p
      role="note"
      aria-label="Which model answered"
      className="rounded-[var(--radius-sm)] border border-info-500/30 bg-info-500/[0.06] px-2.5 py-1.5 text-xs text-slateish-300"
    >
      {note}
    </p>
  );
}
