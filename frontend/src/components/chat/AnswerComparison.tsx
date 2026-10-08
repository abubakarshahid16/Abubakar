import type { AnswerView } from "./AnswerCardContent";
import { Chip, Label, formatDuration } from "./AnswerCardContent";
import { Markdown } from "./Markdown";
import { Citation } from "./EvidencePanel";

/**
 * Plan C3: a comparison's own side breakdown.
 *
 * NOT the generic "Written by the model" card (the answer text is not one
 * model's prose — each side is its own separately retrieved answer, and a
 * side reported absent is a template sentence this app writes, never the
 * model's words for an absence). Each side is its own block: cited to its
 * own passages when its own targeted search found something, a plain note
 * when it did not — never blended into one paragraph a reader would have to
 * pull apart to tell which side said what.
 */
export function ComparisonAnswer({
  view,
  onSelectSource,
  activeSource,
}: {
  view: AnswerView;
  onSelectSource: (i: number) => void;
  activeSource: number | null;
}) {
  const sides = view.comparison?.sides ?? [];
  const family = view.comparison?.family ?? null;
  // `chat_comparison.compare` joins each side's own paragraph with "\n\n", in
  // the SAME order as `sides` - never re-parsed by content, just re-split
  // positionally, since the backend is the one place that decided the order.
  const parts = (view.answer ?? "").split("\n\n");
  // Citation numbers are assigned by the server in `view.passages`' own
  // order (chat_presentation.sources), which is every FOUND side's passages
  // concatenated in the same order as `sides` - so each side's own chips are
  // a contiguous run, found here by matching document ids back to that side.
  let chipCursor = 0;

  return (
    <div className="surface-card accent-edge rounded-[var(--radius-md)] border border-info-500/30 bg-info-500/[0.05] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label tone="generated">
          {family
            ? `Searched ${family.searched.length} standards, each on its own`
            : `Compared across ${sides.length || 2} named sides`}
        </Label>
        {view.seconds != null && (
          <span className="font-mono text-xs text-slateish-500">
            {formatDuration(view.seconds)}
          </span>
        )}
      </div>

      {family && (
        <p className="mt-2 text-sm text-slateish-300" data-testid="family-note">
          {family.note}
        </p>
      )}

      {sides.map((side, i) => {
        const prefix = `${side.name}: `;
        // Each side carries its OWN text and its own run of sources. The
        // positional split below is only for an answer stored before they did
        // (a side's text can contain a blank line, which shifts every later
        // side - the reason the server now sends `text` per side).
        const hasOwnText = typeof side.text === "string";
        const raw = hasOwnText ? (side.text as string) : (parts[i] ?? "");
        const text = !hasOwnText && raw.startsWith(prefix) ? raw.slice(prefix.length) : raw;
        // "Not found in the pages read" is only ever said for a side whose own
        // search ran; a side that was never searched is "not among the
        // documents you can read", whatever its answer_type says.
        const notInLibrary = side.answer_type === "not_in_library" || side.searched === false;
        const notFound = !notInLibrary && side.answer_type === "insufficient_evidence";
        // #451: a side that failed, was stopped or could not be supported is
        // NOT "not found". It says it could not be checked, and why.
        const couldNotCheck = !notInLibrary && side.answer_type === "could_not_be_checked";
        const chipIndexes: number[] = [];
        if (!notFound && !notInLibrary && !couldNotCheck) {
          if (typeof side.source_start === "number" && typeof side.source_count === "number") {
            for (let k = 0; k < side.source_count; k += 1) {
              chipIndexes.push(side.source_start + k);
            }
          } else {
            for (const p of view.passages) {
              if (side.document_ids.includes(p.document_id)) {
                chipIndexes.push(chipCursor);
                chipCursor += 1;
              }
            }
          }
        }
        return (
          <div
            key={side.name}
            className={i === 0 ? "mt-3" : "mt-3 border-t border-ink-700/60 pt-3"}
          >
            <p className="text-xs uppercase tracking-wide text-slateish-500">{side.name}</p>
            {notInLibrary ? (
              <p className="mt-1 text-sm italic text-slateish-400">
                Not among the documents you can read.
              </p>
            ) : couldNotCheck ? (
              <p className="mt-1 text-sm text-warn-500" data-testid="side-could-not-be-checked">
                Could not be checked{side.reason ? `: ${side.reason}` : ""}.
                Nothing can be concluded about this side.
              </p>
            ) : notFound ? (
              <p className="mt-1 text-sm italic text-slateish-400">
                Not found in the pages read.
              </p>
            ) : (
              <>
                {/* The same renderer the ordinary answer uses: bullets and
                    **bold** are laid out, never shown as raw asterisks. Its
                    [S#] markers carry the GLOBAL numbers the server wrote
                    (`_renumber`), so n-1 indexes `view.passages` directly. */}
                <Markdown
                  className="mt-1"
                  text={text}
                  onCite={onSelectSource}
                  activeSource={activeSource}
                />
                {chipIndexes.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap items-baseline gap-2">
                    {chipIndexes.map((idx) => {
                      const passage = view.passages[idx];
                      return passage ? (
                        <span key={idx} className="inline-flex items-center gap-1">
                          <Chip
                            n={idx + 1}
                            active={activeSource === idx}
                            onClick={() => onSelectSource(idx)}
                          />
                          <Citation passage={passage} />
                        </span>
                      ) : null;
                    })}
                  </div>
                )}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
