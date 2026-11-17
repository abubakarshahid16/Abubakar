"""No AI text is stored cut (owner, 15 Nov 2026: completeness rule 3; order 14 W-C6).

The AI reviewer's own words (a rule line's `reasoning` and `comment`; a general review line's comment, finding, note or concern)
are stored WHOLE (`whole`). Before this, three writers shortened them before the line was stored, with no mark: the general
review cut a comment at its prompt's word limit, the rule review kept two "sentences" (a split that also broke at "e.g.") and
cut a comment at 40 words and 160 characters. A cut made before the file is invisible to the file's own cut check, so this
module checks the STORED lines against what the AI really sent, kept in the run's own record (`trace.jsonl`: each item's
answers; `steps/*.json`: each general review reply):

  * `cuts_of_run`: every stored line whose AI words are only the start of words the AI sent (counts and ids only, never text).
  * `check`: the plain sentences `crs_completeness` adds to what is missing, so a file over such a line is refused; and the
    sentence it SAYS when a run keeps no record (its lines cannot be checked).
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

#: The AI's reasoning is shown WHOLE (order 14 W-C6, review of PR #1890): every sentence and every word. Only a true internal code is
#: replaced, IN PLACE, by a mark that says what it replaced: an item id, a model name. A reason code in snake case is said in its
#: words (`crs_ai_words.code_phrase`). A plain word (guard, gate, tier, lane) is never a reason to leave anything out.
ID_MARK = "[internal item id not shown]"
MODEL_MARK = "[model name not shown]"
_MODEL_TAG = re.compile(
    r"\b(?:claude|sonnet|opus|haiku|gpt|qwen|llama|mistral|gemma|gemini)[\w.:/-]*\d[\w.:/-]*",
    re.IGNORECASE,
)


def _model_names() -> re.Pattern | None:
    from . import crs_ai_words as words

    names = sorted((m for m in words._model_ids() if m), key=len, reverse=True)
    return (
        re.compile("|".join(re.escape(m) for m in names), re.IGNORECASE)
        if names
        else None
    )


def plain_whole(text: object) -> str:
    """The AI's reasoning for a reader, WHOLE: ids and model names replaced in place by their marks, reason codes in words."""
    from . import crs_ai_words as words

    out = words._ID_RE.sub(ID_MARK, whole(text))
    if (names := _model_names()) is not None:
        out = names.sub(MODEL_MARK, out)
    out = _MODEL_TAG.sub(MODEL_MARK, out)
    return words._SNAKE.sub(lambda m: words.code_phrase(m.group(0)), out)


def reasoning_left_out(stored: object, shown: object) -> int:
    """1 when the shown cell does not hold the stored reasoning whole (with only the in-place marks of `plain_whole`), else 0."""
    want = plain_whole(stored)
    return 0 if not want or want in whole(shown) else 1


# ---------------------------------------------------------------- the run's record

_QUOTE_KEYS = ("quote", "quote_a", "quote_b", "quote_paper", "quote_other")


def _fold(text: Any) -> str:
    return " ".join(tokens(text))


def _quotes_of(obj: Mapping) -> set[str]:
    """The folded texts of the quotes an answer (or a line) carries; a checklist answer's own `paper_quote` too."""
    got = {
        _fold(q.get("text"))
        for k in _QUOTE_KEYS
        if isinstance(q := obj.get(k), Mapping) and q.get("text")
    }
    if obj.get("paper_quote"):
        got.add(_fold(obj["paper_quote"]))
    return {q for q in got if q}


def _answers(obj: Any) -> Iterable[dict]:
    """Every dict of a general reply that carries the AI's own words (a comment, a finding, a checklist answer)."""
    if isinstance(obj, Mapping):
        if any(
            isinstance(obj.get(k), str) and obj.get(k).strip() for k in GENERAL_KEYS
        ):
            yield {
                "item": str(obj.get("item_id") or "") or None,
                "quotes": _quotes_of(obj),
                "words": [
                    obj[k]
                    for k in GENERAL_KEYS
                    if isinstance(obj.get(k), str) and obj[k].strip()
                ],
            }
        for v in obj.values():
            yield from _answers(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _answers(v)


def record(folder: Path) -> dict | None:
    """{"items": item id -> [lead answers], "general": [answers]} from the run's folder, or None when the folder keeps no record
    (then the stored lines cannot be checked, and the check SAYS so: `check`)."""
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
                if (
                    isinstance(rec, dict)
                    and rec.get("type") == "item"
                    and isinstance(rec.get("lead_answer"), dict)
                ):
                    # the line is built from the FIRST reader's answer (`agent_review_decide`): never a second reader's
                    items.setdefault(str(rec.get("item_id")), []).append(
                        rec["lead_answer"]
                    )
    general: list[dict] = []
    for path in sorted(steps.glob("*.json")) if steps.is_dir() else []:
        try:
            got = parse_json_object(
                json.loads(path.read_text(encoding="utf-8")).get("text") or ""
            )
        except (ValueError, OSError, AttributeError):
            continue
        general.extend(_answers(got))
    return {"items": items, "general": general}


def _own_answers(line: Mapping, general: list[dict]) -> list[dict]:
    """The answers a general line was built from: the same checklist item, else the same quote(s). Never another line's answer."""
    item = str(line.get("checklist_item") or "") or None
    if item:
        return [a for a in general if a["item"] == item]
    quotes = _quotes_of(line)
    return [a for a in general if quotes and quotes <= a["quotes"]] if quotes else []


def line_cuts(line: Mapping, rec: Mapping) -> list[tuple[str, str]]:
    """[(key, the whole words received)] for every AI text of the stored line that is only the start of what the AI sent for
    THIS line. A line that holds any of its own answers whole is not cut."""
    if line.get("general"):
        text = line.get("text")
        own = [v for a in _own_answers(line, rec["general"]) for v in a["words"]]
        if any(_holds(tokens(text), tokens(v)) for v in own if tokens(v)):
            return []
        cut = [v for v in own if cut_inside(text, v)]
        return [("text", max(cut, key=len))] if cut else []
    out: list[tuple[str, str]] = []
    answers = rec["items"].get(str(line.get("item_id")), [])
    for key in RULE_KEYS:
        got = [a.get(key) for a in answers if isinstance(a.get(key), str)]
        if not line.get(key) or any(tokens(v) == tokens(line.get(key)) for v in got):
            continue
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


NOT_CHECKED = (
    "the AI lines of this review could not be checked for a text cut before it was stored: "
    "the run keeps no record of what the AI sent"
)


def check(run_id: str | None) -> dict:
    """{"problems": one sentence per line stored cut (ids and counts only), "unchecked": NOT_CHECKED when the run has lines and
    no record, else None}. `crs_completeness` refuses a file over a problem and SAYS the unchecked sentence."""
    if not run_id:
        return {"problems": [], "unchecked": None}
    from .agent_review_jobs import run_dir
    from .db import connect

    got = cuts_of_run(connect(), run_id, run_dir(run_id))
    problems = [
        f"the AI line {c['item_id']} was stored cut before this file (only the start of the AI's {c['received']} words was kept, "
        "with no mark); its whole text is in the run's record (scripts/restore_whole_ai_text.py puts it back)"
        for c in got["cut"]
    ]
    return {
        "problems": problems,
        "unchecked": NOT_CHECKED if not got["checked"] and got["lines"] else None,
    }


def problems(run_id: str | None) -> list[str]:
    return check(run_id)["problems"]


def _restored_text(text: str, received: str) -> str:
    """The general line's text with the cut start of `received` replaced by all of it."""
    words = whole(received).split()
    for n in range(len(words) - 1, 0, -1):
        part = " ".join(words[:n])
        if part in text:
            return text.replace(part, " ".join(words), 1)
    return text


def restore(conn, run_id: str, folder: Path) -> int:
    """Put the whole AI words back on every line of the run stored cut, from the run's record; returns the lines changed. Only
    `line_json`, and the `reason` column of a GENERAL line (that column is its text); a rule line's `reason` column is never
    rewritten. A second pass changes nothing. The caller holds the write (a live database only through `live_guard`)."""
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
            if line.get("general"):
                conn.execute(
                    "UPDATE agent_review_line SET line_json = ?, reason = ? WHERE run_id = ? AND item_id = ?",
                    (
                        json.dumps(line, ensure_ascii=False, default=str),
                        line["text"],
                        run_id,
                        item,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE agent_review_line SET line_json = ? WHERE run_id = ? AND item_id = ?",
                    (json.dumps(line, ensure_ascii=False, default=str), run_id, item),
                )
            changed += 1
    return changed
