"""Cuts to the AI reader's reply length (order 242.1), each behind a switch.

WHY. Measured on a real sheet with the 35B model: about 95% of the AI time is
the model WRITING replies (a reply averaged 477 tokens; 21 of 119 replies made
61% of all reply tokens; 5 hit the 2,048-token cap and were thrown away), and
reading the prompt cost 0.5 of 13.4 minutes. So every cut here makes the model
write less. None changes a gate: the quote must still be on the page, the value
and label inside it, two runs must agree.

THE SWITCH. `DATASHEET_READER_SPEED` (settings.datasheet_reader_speed): a
comma-separated list of the cuts to apply, empty (none, the reader exactly as
before) by default. Separate names so a measurement can tell which cut did what:

  short_quote      the quote is only the label and value cells, as short as
                   possible (the reply carried a quote of up to 240 characters
                   per field); the form's schema allows at most `SHORT_QUOTE_CHARS`.
  skip_form_read   the whole-page reading is told which fields the form reader
                   already read on that page and skips them (they were read twice
                   and 58 of them agreed on the measured sheet). TRADE-OFF, said
                   plainly: for those fields the whole-page pass is no longer an
                   independent second reading, so a field the page states twice
                   with two values is caught by the form reader's own per-page
                   handling only.
  presplit         a page that looks dense (`DENSE_LINES`, or N for `presplit=N`, lines holding a
                   digit) is read in two parts at once instead of whole, then
                   halved after being cut off: the whole-page attempt that hit
                   the output cap was two wasted runs.

  wide_cap         the whole-page reader's answer budget is `WIDE_CAP_TOKENS` (4,096) instead
                   of 2,048, so a dense page's reply is not cut off and thrown away. THE
                   ALTERNATIVE TO `presplit`, which has a fidelity cost: a page read in
                   parts is read without the column names above the cut, so its readings are
                   marked `kind_unconfirmed` (for an engineer) and a quote that spans the cut
                   is refused (`datasheet_ai._part_fact`); that is where `presplit` lost facts.

  skip_agreed_pages[=N]
                   the whole-page call is NOT made for a page the form reader read fully
                   (`agreed_pages`): no error, no refused reading, at least one reading, and
                   at most N (default `UNEXPLAINED_NUMBERS`) numbers on the page that no
                   reading's quote or value carries. The form's readings stand for those
                   pages. This is where the minutes are (the reader is 12.1 of 13.6 minutes
                   on the measured sheet). The count of such pages is reported for every run
                   (`pages_fully_agreed`), switch or not.

Unknown names are ignored (and listed by `unknown`). Pure functions; no model.
"""

from __future__ import annotations

import copy
import re
from contextlib import contextmanager
from contextvars import ContextVar

from .config import settings

SHORT_QUOTE, SKIP_FORM_READ, PRESPLIT = "short_quote", "skip_form_read", "presplit"
WIDE_CAP = "wide_cap"
SKIP_AGREED = "skip_agreed_pages"
CUTS = (SHORT_QUOTE, SKIP_FORM_READ, PRESPLIT, WIDE_CAP, SKIP_AGREED)
#: A page counts as fully agreed with at most this many numbers its readings do not carry.
UNEXPLAINED_NUMBERS = 2
#: The whole-page reader's answer budget with `wide_cap` (the form reader already has this).
WIDE_CAP_TOKENS = 4096
#: The longest quote the form's answer schema allows when `short_quote` is on.
SHORT_QUOTE_CHARS = 120
#: A page with at least this many lines holding a digit is read in parts at once.
DENSE_LINES = 40

_QUOTE_NEEDLE = re.compile(
    r"quote\s+is the EXACT words[^\n]*(?:\n[^\n]+)*?Never write a quote that is not on the page\."
)
SHORT_QUOTE_RULE = (
    "quote is the shortest EXACT span of the page (usually under 80 characters,"
    " copied character for character) that holds the field's label cell and its"
    " value cell. Both the label and the value must be inside the quote. Never"
    " write a quote that is not on the page."
)


def _named() -> list[str]:
    """The setting's entries, lowercased: `name` or `name=number`."""
    raw = str(getattr(settings, "datasheet_reader_speed", "") or "")
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def _name(entry: str) -> str:
    return entry.split("=", 1)[0].strip()


def on() -> frozenset[str]:
    """The cuts switched on."""
    return frozenset(name for name in map(_name, _named()) if name in CUTS)


def unknown() -> list[str]:
    """Names in the setting that are not a cut (ignored, but worth a warning)."""
    return [name for name in map(_name, _named()) if name not in CUTS]


def _number_after(name: str, default: int) -> int:
    for entry in _named():
        key, _, number = entry.partition("=")
        if key.strip() == name and number.strip().isdigit():
            return int(number)
    return default


def unexplained_numbers(page_text: str, accepted: list[dict]) -> int:
    """How many distinct numbers the page prints that no accepted reading carries
    (in its value or its quote)."""
    from . import numparse

    carried: set = set()
    for fact in accepted:
        carried |= numparse.number_keys(
            f"{fact.get('value') or ''} {fact.get('quote') or ''}"
        )
    return len(numparse.number_keys(page_text or "") - carried)


def agreed_pages(texts: dict[int, str], form_run: dict | None) -> list[int]:
    """The pages the form reader read FULLY: read without error, no refused
    reading, at least one accepted reading, and few numbers it did not carry.
    Computed for every run (a measurement); `skip_agreed_pages` acts on it."""
    allowed = _number_after(SKIP_AGREED, UNEXPLAINED_NUMBERS)
    out = []
    for page, read in sorted(((form_run or {}).get("pages") or {}).items()):
        accepted = read.get("accepted") or []
        if (
            read.get("error")
            or read.get("rejected")
            or not accepted
            or page not in texts
        ):
            continue
        if unexplained_numbers(texts[page], accepted) <= allowed:
            out.append(page)
    return out


def pages_to_ask(texts: dict[int, str], agreed: list[int]) -> dict[int, str]:
    """The pages the whole-page call is made for: all of them, less the fully
    agreed ones when `skip_agreed_pages` is on."""
    if SKIP_AGREED not in on():
        return texts
    return {page: text for page, text in texts.items() if page not in agreed}


def predict_cap(default: int) -> int:
    """The whole-page reader's answer budget: `WIDE_CAP_TOKENS` with `wide_cap`."""
    return WIDE_CAP_TOKENS if WIDE_CAP in on() else default


def dense_lines() -> int:
    """The dense-page threshold: `presplit=60` in the setting, else `DENSE_LINES`.
    A value that is not a positive whole number is ignored."""
    for entry in _named():
        name, _, number = entry.partition("=")
        if name.strip() == PRESPLIT and number.strip().isdigit() and int(number) > 0:
            return int(number)
    return DENSE_LINES


def shorten_schema(schema: dict) -> dict:
    """The form's answer schema with the shorter quote limit when `short_quote`
    is on (a copy); the same schema when it is off."""
    if SHORT_QUOTE not in on():
        return schema
    out = copy.deepcopy(schema)
    out["properties"]["fields"]["items"]["properties"]["quote"]["maxLength"] = (
        SHORT_QUOTE_CHARS
    )
    return out


def version(prompt_version: str) -> str:
    """The prompt version, marked when a cut changes the prompt or the schema
    (a stored answer to the other prompt is then not reused)."""
    return f"{prompt_version}+{SHORT_QUOTE}" if SHORT_QUOTE in on() else prompt_version


def shorten_quote_rule(prompt: str) -> str:
    """`prompt` with its quote paragraph replaced by `SHORT_QUOTE_RULE` when
    `short_quote` is on; the same text when it is off or the paragraph is not
    found (a changed prompt never breaks the reader)."""
    if SHORT_QUOTE not in on():
        return prompt
    return _QUOTE_NEEDLE.sub(SHORT_QUOTE_RULE, prompt, count=1)


def form_read_labels(form_run: dict | None) -> dict[int, list[str]]:
    """{page: the labels of the facts the form reader read on it}, for the
    whole-page pass to skip. {} unless `skip_form_read` is on."""
    if SKIP_FORM_READ not in on() or not form_run:
        return {}
    out: dict[int, list[str]] = {}
    for page, read in (form_run.get("pages") or {}).items():
        if read.get("error"):
            continue
        labels = [f["field"] for f in read.get("accepted") or [] if f.get("field")]
        if labels:
            out[page] = list(dict.fromkeys(labels))
    return out


_SKIP: ContextVar[dict[int, list[str]] | None] = ContextVar(
    "reader_speed_skip", default=None
)


@contextmanager
def skipping(labels: dict[int, list[str]]):
    """Inside the block the whole-page reading skips `labels[page]` on each page."""
    token = _SKIP.set(labels)
    try:
        yield
    finally:
        _SKIP.reset(token)


def read_page(page_text: str, page_no: int, model_call, cut_off):
    """`claude_datasheet.read_page` for one page, with the
    cuts: the labels to skip on this page (`skipping`), and a dense page treated
    as already cut off (`cut_off` is the reader's own exception, so it reads the
    page in parts at once, the way it does after a cut-off, without first
    spending two runs on a reply that would hit the cap)."""
    if dense(page_text):
        raise cut_off(None)
    from . import claude_datasheet  # at call time: it imports this module

    known = (_SKIP.get() or {}).get(page_no)
    return claude_datasheet.read_page(page_text, page_no, known, model_call)


def dense(page_text: str) -> bool:
    """True when `presplit` is on and the page has `DENSE_LINES` or more lines
    with a digit in them (a proxy for how many values the reply must carry)."""
    if PRESPLIT not in on():
        return False
    return (
        sum(1 for line in (page_text or "").splitlines() if re.search(r"\d", line))
        >= dense_lines()
    )
