"""No AI text is stored cut (owner, 15 Nov 2026: completeness rule 3; order 14 W-C6).

The AI reviewer's own words (a rule line's `reasoning` and `comment`; a general review line's comment, finding, note or concern)
are stored WHOLE (`whole`). Before this, three writers shortened them before the line was stored, with no mark: the general
review cut a comment at its prompt's word limit, the rule review kept two "sentences" (a split that also broke at "e.g.") and
cut a comment at 40 words and 160 characters. A cut made before the file is invisible to the file's own cut check, so this
module checks the STORED lines against what the AI really sent, kept in the run's own record (`trace.jsonl`: each item's
answers; `steps/*.json`: each general review reply):

  * `cuts_of_run`: every stored line whose AI words are only the start of words the AI sent (counts and ids only, never text).
  * `problems`: the plain sentences `crs_completeness` adds to what is missing, so a file over such a line is refused.
  * `restore`: puts the whole words back from the record (no model call, no cost).

A reply the model itself cut at its length limit is never used as a line: the part says so in plain words (`REPLY_CUT`) and the
text received stays in the run's record. General code (rule 13): nothing here knows a layout or a paper.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

#: The words a line or a part carries when the model's reply stopped at its length limit (visible on every surface).
REPLY_CUT = "the AI's reply was cut off by its length limit; nothing of it was used (the text received is kept in the run's record)"
STOP_MAX_TOKENS = "stop_max_tokens"
#: The AI's own words on a rule line, and in a general review reply.
RULE_KEYS = ("reasoning", "comment")
GENERAL_KEYS = ("comment", "what", "note", "concern")
#: A general line holds the AI's words inside code's own frame: a cut is seen when at least this many first words are there.
PREFIX_WORDS = 6
_WORD = re.compile(r"[^\W_]+")
_QUOTES = re.compile("[\"'\u2018\u2019\u201c\u201d]")


def whole(text: Any) -> str:
    """The text with its spaces made single, NEVER shortened: the AI's word limit is the prompt's to ask, not code's to enforce."""
    return " ".join(str(text or "").split())


def tokens(text: Any) -> list[str]:
    return [w.casefold() for w in _WORD.findall(_QUOTES.sub("", str(text or "")))]


def cut_from(stored: Any, received: Any) -> bool:
    """True when `stored` keeps only the START of `received`: its words are a strict prefix of the words received (the last stored
    word may itself be cut)."""
    s, r = tokens(stored), tokens(received)
    if not s or len(s) > len(r) or s == r:
        return False
    if s[:-1] != r[: len(s) - 1] or not r[len(s) - 1].startswith(s[-1]):
        return False
    return len(s) < len(r) or s[-1] != r[len(s) - 1]


def _holds(hay: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(hay[i : i + n] == needle for i in range(len(hay) - n + 1))


def cut_inside(text: Any, received: Any) -> bool:
    """True when the line `text` holds the start of `received` (at least PREFIX_WORDS words) but not all of it."""
    t, r = tokens(text), tokens(received)
    if len(r) <= PREFIX_WORDS or _holds(t, r):
        return False
    return _holds(t, r[:PREFIX_WORDS])


# ---------------------------------------------------------------- the reader's view of the AI's reasoning

#: The AI's reasoning is shown WHOLE (order 14 W-C6): a sentence is left out only when it names an internal code, and then this
#: mark says so where it was; the "nothing to do" words are never taken out of it (that cut a sentence in two with no mark).
LEFT_OUT = (
    "[{n} sentence(s) of the AI's reasoning not shown here: they name internal codes]"
)
_LEFT_OUT_RE = re.compile(
    r"\[(\d+) sentence\(s\) of the AI's reasoning not shown here: they name internal codes\]"
)


def _reader_sentence(sentence: str) -> str:
    """One sentence of the AI's own text for a reader: ids out, reason codes in words (the same two steps as `crs_ai_words.plain`)."""
    from . import crs_ai_words as words

    return " ".join(
        words._SNAKE.sub(
            lambda m: words.code_phrase(m.group(0)), words._ID_RE.sub("", sentence)
        ).split()
    )


def plain_whole(text: object) -> str:
    """The AI's reasoning for a reader, WHOLE: every sentence in order (`_reader_sentence`), a sentence that still names an internal
    code left out with the visible mark `LEFT_OUT` in its place. Never the "nothing to do" filter, never a cut inside a sentence."""
    from . import crs_ai_words as words

    out: list[str] = []
    left = 0
    for s in words._SENTENCES.split(whole(text)):
        said = _reader_sentence(s)
        if not said:
            continue
        if words.has_banned(said):
            left += 1
            continue
        if left:
            out.append(LEFT_OUT.format(n=left))
            left = 0
        out.append(said)
    if left:
        out.append(LEFT_OUT.format(n=left))
    return " ".join(out)


def reasoning_left_out(stored: object, shown: object) -> int:
    """How many sentences of the stored reasoning are NOT in the shown cell without the mark for them (0 when whole or marked)."""
    from . import crs_ai_words as words

    cell = whole(shown)
    marked = sum(int(m.group(1)) for m in _LEFT_OUT_RE.finditer(cell))
    missing = sum(
        1
        for s in words._SENTENCES.split(whole(stored))
        if (said := _reader_sentence(s)) and said not in cell
    )
    return max(0, missing - marked)


# ---------------------------------------------------------------- the run's record


def _strings(obj: Any, keys: tuple[str, ...]) -> Iterable[str]:
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if k in keys and isinstance(v, str) and v.strip():
                yield v
            else:
                yield from _strings(v, keys)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v, keys)


def record(folder: Path) -> dict | None:
    """{"items": item id -> [answers], "general": [the AI's words of every general reply]} from the run's folder, or None when the
    folder keeps no record (then the stored lines cannot be checked, and the caller says so)."""
    from .agent_claude import parse_json_object

    trace, steps = folder / "trace.jsonl", folder / "steps"
    if not trace.is_file() and not steps.is_dir():
        return None
    items: dict[str, list[dict]] = {}
    if trace.is_file():
        with trace.open(encoding="utf-8") as fh:
            for raw in fh:
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(rec, dict) or rec.get("type") != "item":
                    continue
                got = [
                    a
                    for k, a in rec.items()
                    if k.endswith("_answer") and isinstance(a, dict)
                ]
                items.setdefault(str(rec.get("item_id")), []).extend(got)
    general: list[str] = []
    for path in sorted(steps.glob("*.json")) if steps.is_dir() else []:
        try:
            got = parse_json_object(
                json.loads(path.read_text(encoding="utf-8")).get("text") or ""
            )
        except (ValueError, OSError, AttributeError):
            continue
        general.extend(dict.fromkeys(_strings(got, GENERAL_KEYS)))
    return {"items": items, "general": general}


def line_cuts(line: Mapping, rec: Mapping) -> list[tuple[str, str]]:
    """[(key, the whole words received)] for every AI text of the stored line that is only the start of what the AI sent."""
    out: list[tuple[str, str]] = []
    if line.get("general"):
        text = line.get("text")
        out += [("text", v) for v in rec["general"] if cut_inside(text, v)]
        return out
    answers = rec["items"].get(str(line.get("item_id")), [])
    for key in RULE_KEYS:
        got = [a.get(key) for a in answers if isinstance(a.get(key), str)]
        cut = [v for v in got if cut_from(line.get(key), v)]
        if cut:
            out.append((key, max(cut, key=len)))
    return out


def _lines(conn, run_id: str) -> list[tuple[str, dict]]:
    out = []
    for r in conn.execute(
        "SELECT item_id, line_json FROM agent_review_line WHERE run_id = ? ORDER BY item_id",
        (run_id,),
    ):
        try:
            out.append((r[0], json.loads(r[1] or "{}")))
        except ValueError:
            continue
    return out


def cuts_of_run(conn, run_id: str, folder: Path) -> dict:
    """{"checked": the record was there, "lines": stored lines, "cut": [{"item_id", "key", "received"}] (the AI's word count)}."""
    rec = record(folder)
    lines = _lines(conn, run_id)
    if rec is None:
        return {"checked": False, "lines": len(lines), "cut": []}
    cut = []
    for item, line in lines:
        for key, v in line_cuts(line, rec):
            cut.append({"item_id": item, "key": key, "received": len(tokens(v))})
    return {"checked": True, "lines": len(lines), "cut": cut}


def problems(run_id: str | None) -> list[str]:
    """What `crs_completeness` reports for the run's stored lines: one sentence per line stored cut (ids and counts only)."""
    if not run_id:
        return []
    from .agent_review_jobs import run_dir
    from .db import connect

    got = cuts_of_run(connect(), run_id, run_dir(run_id))
    return [
        f"the AI line {c['item_id']} was stored cut before this file (only the start of the AI's {c['received']} words was kept, "
        "with no mark); its whole text is in the run's record (scripts/restore_whole_ai_text.py puts it back)"
        for c in got["cut"]
    ]


def _restored_text(text: str, received: str) -> str:
    """The general line's text with the cut start of `received` replaced by all of it."""
    words = whole(received).split()
    for n in range(len(words) - 1, 0, -1):
        part = " ".join(words[:n])
        if part in text:
            return text.replace(part, " ".join(words), 1)
    return text


def restore(conn, run_id: str, folder: Path) -> int:
    """Put the whole AI words back on every line of the run stored cut, from the run's record. Returns the lines changed. The
    caller holds the write (a live database only through `live_guard.prepare_live_write`)."""
    rec = record(folder)
    if rec is None:
        return 0
    changed = 0
    with conn:
        for item, line in _lines(conn, run_id):
            cuts = line_cuts(line, rec)
            if not cuts:
                continue
            for key, v in cuts:
                line[key] = (
                    _restored_text(str(line.get(key) or ""), v)
                    if line.get("general")
                    else whole(v)
                )
            line["restored_whole_from_record"] = True
            reason = (
                line["text"]
                if line.get("general")
                else str(  # the column `store_line` writes, from the same keys
                    line.get("not_proven_reason")
                    or line.get("reasoning")
                    or line.get("why")
                    or ""
                )
            )
            conn.execute(
                "UPDATE agent_review_line SET line_json = ?, reason = COALESCE(?, reason) WHERE run_id = ? AND item_id = ?",
                (
                    json.dumps(line, ensure_ascii=False, default=str),
                    reason,
                    run_id,
                    item,
                ),
            )
            changed += 1
    return changed
