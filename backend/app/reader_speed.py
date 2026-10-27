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
  presplit         a page that looks dense (`DENSE_LINES` or more lines holding a
                   digit) is read in two parts at once instead of whole, then
                   halved after being cut off: the whole-page attempt that hit
                   the output cap was two wasted runs.

Unknown names are ignored (and listed by `unknown`). Pure functions; no model.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar

from .config import settings

SHORT_QUOTE, SKIP_FORM_READ, PRESPLIT = "short_quote", "skip_form_read", "presplit"
CUTS = (SHORT_QUOTE, SKIP_FORM_READ, PRESPLIT)
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
    raw = str(getattr(settings, "datasheet_reader_speed", "") or "")
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def on() -> frozenset[str]:
    """The cuts switched on."""
    return frozenset(name for name in _named() if name in CUTS)


def unknown() -> list[str]:
    """Names in the setting that are not a cut (ignored, but worth a warning)."""
    return [name for name in _named() if name not in CUTS]


def quote_limit(default: int) -> int:
    return SHORT_QUOTE_CHARS if SHORT_QUOTE in on() else default


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


_SKIP: ContextVar[dict[int, list[str]]] = ContextVar("reader_speed_skip", default={})


@contextmanager
def skipping(labels: dict[int, list[str]]):
    """Inside the block the whole-page reading skips `labels[page]` on each page."""
    token = _SKIP.set(labels)
    try:
        yield
    finally:
        _SKIP.reset(token)


def read_page(read, page_text: str, page_no: int, model_call, cut_off):
    """`read(page_text, page_no, known, model_call)` for one page, with the
    cuts: the labels to skip on this page (`skipping`), and a dense page treated
    as already cut off (`cut_off` is the reader's own exception, so it reads the
    page in parts at once, the way it does after a cut-off, without first
    spending two runs on a reply that would hit the cap)."""
    if dense(page_text):
        raise cut_off(None)
    return read(page_text, page_no, _SKIP.get().get(page_no), model_call)


def dense(page_text: str) -> bool:
    """True when `presplit` is on and the page has `DENSE_LINES` or more lines
    with a digit in them (a proxy for how many values the reply must carry)."""
    if PRESPLIT not in on():
        return False
    return (
        sum(1 for line in (page_text or "").splitlines() if re.search(r"\d", line))
        >= DENSE_LINES
    )
