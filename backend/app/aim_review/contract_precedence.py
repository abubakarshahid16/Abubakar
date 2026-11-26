"""THE ORDER OF PRECEDENCE DECIDES (lead-4, 26 Nov 2026; the u6 miss list: "a precedence order compared but not decided"; behind
AIM_U13_ENABLED, off: no line changes).

A contract states the order in which its parts prevail (a numbered list after a line with the word "precedence",
`contract_checks.precedence_list`). The general review's judge may write that two ranked parts conflict ("Schedule C states 30
days whereas Schedule A states 45 days") and stop there: compared, not decided. The contract itself decides it, so code adds one
sentence to such a comment, from the paper's own list: "The order of precedence (page P) ranks Schedule A above Schedule C, so
Schedule A governs where they differ." The comment stays a Question for the engineer (the parts should still agree).

And a comment that states a ranking the list contradicts ("Schedule C prevails over Schedule A" when the list ranks A first) gets
the list's own correction (`contract_checks.guard_ranking`, the old engine's tested guard, used here unchanged).

Only parts that are ON the list count; a comment naming one ranked part, three, or none, or one that already says which part
prevails, is left as it is. Contract papers only; code reads the paper's own words; no model, no write."""

from __future__ import annotations

import re
from collections import Counter

from .. import contract_checks as CC

#: The judge's words for two parts that do not agree.
_CONFLICT = re.compile(
    r"\b(?:conflicts?|conflicting|inconsisten\w*|contradict\w*|discrepan\w*|differs?|different|mismatch\w*|whereas)\b",
    re.I,
)
#: A comment that already says which part prevails: never added to.
_DECIDED = re.compile(
    r"\b(?:prevails?|governs?|takes? precedence|order of precedence|ranks? (?:above|below|higher|lower|first|ahead))\b",
    re.I,
)


def _ranked_parts(text: str, rank_of: dict, word: str) -> list:
    """The distinct ranked parts the comment names, in the order it names them."""
    out: list = []
    for _start, _end, key in CC._mentions(text, word):
        if key in rank_of and key not in out:
            out.append(key)
    return out


def decide(lines: list[dict], pages: dict[int, str]) -> int:
    """Each AI line's comment completed by the paper's order of precedence, in place. Returns how many comments were completed."""
    ranks = CC.precedence_list(sorted(pages.items()))
    if len(ranks) < 2:
        return 0
    rank_of = {k: (r, p) for r, k, p in ranks}
    word = Counter(k[0] for _r, k, _p in ranks).most_common(1)[0][0]
    done = 0
    for line in lines:
        text = " ".join(str(line.get("comment") or "").split())
        if not text:
            continue
        wrong = CC.guard_ranking(text, ranks)
        if wrong:  # the comment's own ranking contradicts the list: the list's correction is added
            said = wrong.replace(
                "the list on page", "the order of precedence on page", 1
            )
            line["comment"] = f"{text} Note: {said[0].upper()}{said[1:]}."
            done += 1
            continue
        named = _ranked_parts(text, rank_of, word)
        if len(named) != 2 or not _CONFLICT.search(text) or _DECIDED.search(text):
            continue
        a, b = named
        hi, lo = (a, b) if rank_of[a][0] < rank_of[b][0] else (b, a)
        top, low = CC._name((hi, None)), CC._name((lo, None))
        line["comment"] = (
            f"{text} The order of precedence (page {rank_of[hi][1]}) ranks {top} above {low}, so {top} governs where they differ."
        )
        done += 1
    return done
