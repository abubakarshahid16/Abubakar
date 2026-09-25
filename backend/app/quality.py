"""Content-quality gate.

The safety net for failure modes no structural detector anticipated. It must
answer one question: *is there anything here a person could read and use?*

An earlier version scored the whole chunk's averages - alphabetic ratio,
average word length, proportion of word-like tokens. That asks "does this read
like prose", which is the wrong question twice over:

  * A page of exercises whose equations were stripped by PDF extraction is
    mostly numerals, so its averages look terrible, yet it contains the real
    clause "the given vectors are solutions of a system ... Determine whether
    the vectors form a fundamental set". Rejecting it loses real content.
  * A legitimate table NEVER reads like prose. Judging it by prose signals
    rejects every table in the corpus - fatal for engineering specifications,
    which are mostly tables.

So: prose is judged on whether it contains a genuine clause, and tables are
judged on structure. Rejection is reserved for text that is unrecoverable.
"""

from __future__ import annotations

import re
import unicodedata

from . import ligatures
from . import symbols

# Control characters that PDF symbol fonts leave behind. Kept as a module
# constant so extraction and the gate agree on what counts as noise.
_CONTROL_RANGE = "".join(
    chr(c) for c in list(range(0, 9)) + [11, 12] + list(range(14, 32)) + [127]
)
CONTROL_CHARS = re.compile(f"[{re.escape(_CONTROL_RANGE)}]")
_WS = re.compile(r"\s+")
_EDGE_PUNCT = ".,;:!?()[]{}\"'‘’“”·•●"
_VOWELS = set("aeiouyAEIOUY")

# A clause of this many consecutive real words means the chunk carries content
# a person can read, whatever the surrounding numerals look like.
MIN_CLAUSE_WORDS = 6
# Below this many words a chunk is a heading or fragment, judged more leniently.
SHORT_CHUNK_WORDS = 12
MIN_SHORT_CLAUSE_WORDS = 3

# Table structure thresholds.
_TABLE_LABEL = re.compile(r"(?im)^\s*(TABLE|Table|FIGURE|Figure|EXHIBIT|Exhibit)\s*\d")
# A data cell, not a list enumerator. "4.0000" and "-2.5" are cells;
# "7." and "13." are numbered list markers and must not count as data,
# or a line of exercise numbers reads as a table.
_NUMERIC_CELL = re.compile(r"^[-+(]?\d[\d.,%/:–-]*\)?$(?<![.,])")


def normalise_text(text: str) -> str:
    """Strip PDF control-character noise without destroying layout.

    Newlines and tabs survive - table structure depends on them. Everything
    else in the C0/C1 control range is a symbol-font artefact.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\x00", "")
    # keep \n and \t, drop the rest of the control range
    text = CONTROL_CHARS.sub(" ", text)
    # Ligatures whose embedded font mapping is wrong extract as the wrong
    # character entirely - "Introduc,on" for Introduction, "DeEinitions" for
    # Definitions. Repaired HERE, at extraction, because it is a coverage
    # problem and not a retrieval one: no ranking change can match a word that
    # is not in the text. Measured on book4 at 292 of 1,400 pages, and the
    # repair is validated to change nothing across 2,281 clean pages.
    text = ligatures.repair(text)
    # The same class of defect from a symbol font rather than a ligature: the
    # micro sign extracted as a capital P, so "1000 um NDFT" yielded no
    # measurement at all. Narrow by construction and validated over the whole
    # corpus - see symbols.py for what it deliberately does NOT repair.
    text = symbols.repair(text)
    return text


def is_word(token: str) -> bool:
    """A token a person would recognise as a word.

    Letters only (internal hyphen or apostrophe allowed), at least two
    characters, and containing a vowel. The vowel and no-digits rules are what
    separate real words from symbol-font debris like `eabeb2terfcb`, `ea1s`
    and `dn`, which otherwise look alphabetic enough to pass.
    """
    t = token.strip(_EDGE_PUNCT)
    if len(t) < 2:
        return False
    core = t.replace("-", "").replace("'", "").replace("’", "")
    if not core.isalpha():
        return False
    return any(ch in _VOWELS for ch in core)


#: A plain number as written in a requirement: "50", "2.5", "4140", "1/2", "10%".
_MEASURE = re.compile(r"^[-+]?\d+(?:[.,/]\d+)*%?$")


def _is_measure(token: str) -> bool:
    return bool(_MEASURE.match(token.strip(_EDGE_PUNCT)))


def longest_clause(text: str) -> int:
    """Longest run of consecutive real words.

    A number standing BETWEEN two words neither breaks the run nor counts in
    it. Requirement text is full of them - "a surface profile of 50 to 75
    micrometres", "the shaft AISI 4140 for all pumps" - and breaking the run at
    each one made the densest requirement clauses read as debris: B6 measured
    3 of 15 synthetic specification clauses dropped from retrieval that way
    (quality gate and front-matter classifier alike). A number followed by
    another number or ending the text - a table row, a contents column - still
    breaks the run, so number walls and symbol debris stay out.
    """
    tokens = text.split()
    best = run = 0
    for i, token in enumerate(tokens):
        if is_word(token):
            run += 1
            best = max(best, run)
        elif _is_measure(token) and i + 1 < len(tokens) and is_word(tokens[i + 1]):
            # A measurement followed by a word keeps the run going (after a
            # non-word the run is already 0, so the left side needs no check).
            continue
        else:
            run = 0
    return best


def looks_like_table(text: str) -> dict:
    """Structural evidence that this is a real table rather than noise.

    Deliberately independent of prose signals. A table is recognised by a
    label or caption, a header row, and rows of short regular cells - never by
    reading like a sentence.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return {"is_table": False, "reasons": ["empty"], "evidence": {}}

    has_label = bool(_TABLE_LABEL.search(text))
    numeric_lines = sum(1 for line in lines if _NUMERIC_CELL.match(line))
    # a header row: short, wordy, no digits
    header_like = sum(
        1 for line in lines[:6]
        if 0 < len(line) <= 40 and not any(ch.isdigit() for ch in line)
    )
    short_lines = sum(1 for line in lines if len(line) <= 40)
    numeric_ratio = numeric_lines / len(lines)
    short_ratio = short_lines / len(lines)

    evidence = {
        "has_label": has_label,
        "header_like_lines": header_like,
        "numeric_lines": numeric_lines,
        "numeric_ratio": round(numeric_ratio, 3),
        "short_line_ratio": round(short_ratio, 3),
        "lines": len(lines),
    }

    # Structure means regular short lines with a real share of numeric cells.
    structured = short_ratio >= 0.6 and numeric_lines >= 3
    identified = has_label or header_like >= 1

    # A labelled or headed table needs only modest structure.
    if structured and identified:
        return {"is_table": True, "reasons": [], "evidence": evidence}

    # A table chunk that starts mid-table has no label and no header - its
    # first line is already data. Dense regular numeric columns are evidence
    # enough on their own. This is what rescued 31 real tables (population
    # series, Bessel zeros) that were rejected purely for lacking a caption.
    if short_ratio >= 0.9 and numeric_ratio >= 0.55 and len(lines) >= 8:
        return {"is_table": True, "reasons": [], "evidence": evidence}

    # A table can also extract ROW-wise onto a single line:
    #   "0.00 30.0000 30.0000 30.0000 30.0000 ..."
    # Every line-based metric is then zero, so measure the tokens instead.
    tokens = text.split()
    numeric_tokens = sum(1 for t in tokens if _NUMERIC_CELL.match(t))
    token_ratio = numeric_tokens / len(tokens) if tokens else 0.0
    evidence["numeric_tokens"] = numeric_tokens
    evidence["numeric_token_ratio"] = round(token_ratio, 3)
    if numeric_tokens >= 6 and token_ratio >= 0.7:
        return {"is_table": True, "reasons": [], "evidence": evidence}

    reasons = []
    if not structured:
        reasons.append(f"no_regular_structure(short={short_ratio:.2f},num={numeric_lines})")
    if not identified:
        reasons.append("no_label_or_header")
    return {"is_table": False, "reasons": reasons, "evidence": evidence}


def assess(text: str, kind: str = "prose") -> dict:
    """Decide whether a chunk is worth retrieving, and say why not if it isn't."""
    cleaned = _WS.sub(" ", normalise_text(text)).strip()
    if not cleaned:
        return {"ok": False, "reasons": ["empty"], "clause": 0, "kind": kind}

    if kind == "table":
        t = looks_like_table(text)
        # a table with a readable clause in it is fine regardless of structure
        clause = longest_clause(cleaned)
        ok = t["is_table"] or clause >= MIN_CLAUSE_WORDS
        return {
            "ok": ok,
            "reasons": [] if ok else ["not_a_table:" + ";".join(t["reasons"])],
            "clause": clause,
            "kind": kind,
            "table_evidence": t["evidence"],
        }

    clause = longest_clause(cleaned)
    # A short chunk is a heading or a fragment - "Criminal and civil penalties"
    # is real content and can never contain a six-word clause. A LONG chunk
    # with no six-word clause anywhere is debris.
    total_words = len(cleaned.split())
    required = MIN_SHORT_CLAUSE_WORDS if total_words <= SHORT_CHUNK_WORDS else MIN_CLAUSE_WORDS
    if clause >= required:
        return {"ok": True, "reasons": [], "clause": clause, "kind": kind}

    # No readable clause. It may still be a table that was labelled prose.
    t = looks_like_table(text)
    if t["is_table"]:
        return {"ok": True, "reasons": [], "clause": clause, "kind": "table-like"}

    return {
        "ok": False,
        "reasons": [f"no_clause(longest={clause}<{required})"],
        "clause": clause,
        "kind": kind,
    }


def reads_like_language(text: str, kind: str = "prose") -> bool:
    return assess(text, kind)["ok"]
