"""Keep the evidence inside the model's context window, and say when it does not.

`generated_context_chars` is a CHARACTER budget standing in for a TOKEN budget.
That substitution is only valid while the ratio between them is stable, and on
this corpus it is not: measured with the deployed tokenizer, engineering prose
runs at 4.4-5.8 characters per token and a numeric table runs at **1.01**.

Qwen's BPE tokenises digits one at a time. `30.0000` is eight tokens for seven
characters, and a table row of ten such values is seventy.

The consequence was live. Three 1,200-character numeric-table passages from
`book2` build a Tier 2 prompt of **3,645 tokens against a `num_ctx` of 1,536**.
llama.cpp discards the overflow silently: the same prompt sent at the deployed
window reports `prompt_eval_count` of **1,026** - not 1,536, but 510 tokens
BELOW the ceiling - so roughly 72% of the evidence vanishes and the response
carries no signal that it happened. The model then answers from whatever
survived, citing sources it was never shown.

WHY THIS IS AN ESTIMATE AND NOT THE REAL TOKENIZER

The deployed tokenizer is only reachable through Ollama, and both routes to it
were measured and rejected:

  * Probing at a larger `num_ctx` gives a true count, but changing `num_ctx`
    forces a full model reload - measured at 16.0 s up and 16.3 s back, 32 s
    per question on this machine.
  * Probing at the deployed `num_ctx` costs no reload but returns the
    truncated count above, which is indistinguishable from a small prompt.

So the count is computed locally, and it is built to FAIL SAFE: it may
over-estimate, which wastes window, and it must never under-estimate, which is
what lets evidence disappear.

HOW THE ESTIMATE IS BUILT

Two parts, and only one of them is calibrated:

  * A run containing a digit costs one token per byte, plus the bytes of the
    whitespace in front of it. This is the hard byte bound - a byte-level BPE
    emits at most one token per byte - and on numeric tables it is nearly
    exact, because digits do not merge.
  * A run of letters costs bytes / CHARS_PER_WORD_TOKEN. This one IS
    calibrated against the deployed tokenizer, and `test_context_budget.py`
    re-checks it against recorded ground truth.

Calibrated against ten real chunks spanning 0.0% to 71.4% digits, measured
2026-09-05 with qwen3.5:4b itself. Full table in `docs/benchmarks.md`.

IT IS A GUARD, NOT AN ALLOCATOR. When the estimate fits, nothing is changed and
the prompt is built exactly as before - so the common prose case is untouched.
It only intervenes when the estimate says the window would overflow, and then
it trims or drops sources and REPORTS what it removed.
"""

from __future__ import annotations

import math
import re

from .config import settings

#: Bytes of letters per token. The one calibrated number here.
#:
#: 3.5 rather than the 4.4-5.8 characters per token that pure prose measures,
#: because MIXED CONTENT is denser than either extreme. A `book2` chunk with
#: only 4.3% digits costs 3.09 characters per token - the numbers scattered
#: through it break up merges that would otherwise happen in the surrounding
#: words. At 4.0 this estimator under-counted that chunk by 7% (362 against a
#: true 388), which is exactly the silent-truncation failure it exists to
#: prevent, and it was caught by re-checking the published figures rather than
#: by the first calibration pass.
#:
#: Lowering it wastes window; raising it risks silent truncation. Those are not
#: symmetric, which is why it sits below every measured value.
CHARS_PER_WORD_TOKEN = 3.5

#: Applied to the whole estimate, as margin against the corpus being an
#: incomplete sample of what the tokenizer can do.
#:
#: With it, the worst observed estimate is 1.035x the true count - a 3.5%
#: margin over twelve measured chunks spanning 0.0% to 75.1% digits. Without
#: it the worst is 1.006x, which is too little to trust against text nobody has
#: measured yet.
#:
#: THE MARGIN IS THE ONLY GUARD. There is no post-hoc check available: a
#: truncated prompt reports FEWER tokens evaluated than the window holds, and a
#: cached prefix reports fewer still, so a low count cannot distinguish
#: "truncated" from "seen before" - the confound that made the first attempt at
#: measuring this read 1,026 tokens for a 3,645-token prompt.
SAFETY = 1.05

#: Below this, a trimmed passage is dropped instead. A 40-character fragment
#: of a table is not evidence, and presenting it as a source invites the model
#: to cite it.
MIN_USEFUL_CHARS = 200

_RUN = re.compile(r"(\s*)(\S+)")


def estimate_tokens(text: str) -> int:
    """An upper bound on what the deployed tokenizer will charge for `text`."""
    digit_bytes = 0
    word_bytes = 0
    for whitespace, run in _RUN.findall(text):
        size = len(run.encode("utf-8"))
        if any(ch.isdigit() for ch in run):
            # Digits do not merge, and neither does the newline-plus-indent
            # that separates table columns.
            digit_bytes += size + len(whitespace.encode("utf-8"))
        else:
            # The space in front of a word merges into it, so it is not
            # charged separately.
            word_bytes += size
    raw = digit_bytes + math.ceil(word_bytes / CHARS_PER_WORD_TOKEN)
    return math.ceil(raw * SAFETY)


def evidence_budget() -> int:
    """Tokens available for the prompt, once the answer's own budget is held back.

    `num_predict` is a ceiling the generation may use in full, so the space for
    it has to be reserved rather than hoped for.
    """
    return settings.num_ctx - settings.max_output_tokens


def _cut_to_tokens(text: str, budget: int) -> str:
    """The longest prefix of `text` whose estimate fits in `budget`.

    Binary search on characters rather than a ratio, because the ratio is the
    thing that is not stable. Cut back to a line boundary where one is close,
    so a table row is not severed mid-number.
    """
    if budget <= 0:
        return ""
    if estimate_tokens(text) <= budget:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_tokens(text[:mid]) <= budget:
            low = mid
        else:
            high = mid - 1
    cut = text[:low]
    breakpoint_ = max(cut.rfind("\n"), cut.rfind(". "))
    if breakpoint_ > low * 0.6:
        cut = cut[: breakpoint_ + 1]
    return cut.rstrip()


def fit_passages(
    passages: list[dict], overhead: str, budget: int | None = None
) -> tuple[list[dict], list[dict]]:
    """Trim or drop passages until the prompt is certain to fit.

    `overhead` is everything in the prompt that is not passage text - the
    system prompt, the question, the source headers - measured rather than
    assumed, so a long question cannot quietly push the evidence over.

    Returns the passages to use and a record of what was removed. Nothing is
    ever removed silently: the record is carried on the answer, because
    `done_reason == "length"` already tells the reader when the OUTPUT was cut
    off and input truncation deserves the same treatment.
    """
    budget = evidence_budget() if budget is None else budget
    room = budget - estimate_tokens(overhead)

    def record(index, passage, action, kept_chars, text):
        return {
            "index": index,
            "filename": passage.get("filename"),
            "page_start": passage.get("page_start"),
            "action": action,
            "characters_kept": kept_chars,
            "characters_dropped": len(text) - kept_chars,
        }

    kept: list[dict] = []
    removed: list[dict] = []
    for index, passage in enumerate(passages, start=1):
        text = passage.get("text") or ""

        # Once anything has been removed, everything after it goes too. The
        # citation markers are positional - [S1], [S2], [S3] index into the
        # list handed to the model - so keeping source 3 after dropping source
        # 2 would renumber them, and every citation in the answer would point
        # one place to the left.
        if removed:
            removed.append(record(index, passage, "dropped", 0, text))
            continue

        cost = estimate_tokens(text)
        if cost <= room:
            kept.append(passage)
            room -= cost
            continue

        shortened = _cut_to_tokens(text, room)
        # A fragment too short to carry a fact is worse than an honest gap: it
        # reads as evidence and is not one.
        if len(shortened) >= MIN_USEFUL_CHARS:
            kept.append({**passage, "text": shortened})
            removed.append(record(index, passage, "trimmed", len(shortened), text))
        else:
            removed.append(record(index, passage, "dropped", 0, text))
    return kept, removed
