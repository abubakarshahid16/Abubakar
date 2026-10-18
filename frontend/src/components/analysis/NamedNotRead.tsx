/**
 * #633 item 1: documents the question NAMED that could not be read - misspelt,
 * absent from the library, or not granted to the caller. The answer did not
 * examine them, and until now nothing on the screen said so: the API returned
 * `named_documents_not_read` and no component read it.
 */
export function NamedNotRead({ names, what }: { names: readonly string[]; what: string }) {
  const seen = [...new Set(names.map((n) => n.trim()).filter(Boolean))];
  if (seen.length === 0) return null;
  return (
    <p role="status" data-testid="named-not-read"
      className="rounded-[var(--radius-sm)] border border-warn-500/40 bg-warn-500/10 px-3 py-2 text-sm text-warn-500">
      {seen.length === 1 ? "A document named in the question was not read: " : `${seen.length} documents named in the question were not read: `}
      <span className="font-semibold">{seen.join(", ")}</span>
      {`. The ${what} did not examine ${seen.length === 1 ? "it" : "them"} - check the name, that it is in the library, and that you may read it.`}
    </p>
  );
}
