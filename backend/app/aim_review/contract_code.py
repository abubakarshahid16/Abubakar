"""CONTRACT CODE CHECKS (order 14, builder C, 19 Nov 2026): what code alone proves on a contract's own words, and the fixed contract
checklist that every contract review judges in addition to the checklist written from the standards.

Code checks (each line carries the page and a quote that verifies on that page; `lines`):
  amount_words   an amount or a percentage written in words and in figures in ONE quote ("Ten (10)", "five percent (5%)",
                 "<currency name> <words> (<code> <figures>)"): the two numbers differ, or the currency named in words is not the
                 currency of the code in brackets -> "Not met, proven by code".
  dates          a start date and an end date in one quote (unambiguous forms only: 3 March 2027, March 3, 2027, 2027-03-03; 03/04
                 gives no verdict): the end is before the start, or the start plus the duration stated between them is not the end
                 -> "Not met, proven by code".
  splits         percentages split with "/" in one bracket ("(60% X / 40% Y)"): a sentence that says "equally" with unequal parts
                 -> "Not met, proven by code"; parts that do not add up to 100 -> a Question.
  percent_values two different percentages stated as the same kind of statement (a cap: "not exceed", "not more than"; or a rate:
                 "equal to", "equivalent to") on the same base ("of the <base>") under the same clause heading: the same subject
                 words -> "Not met, proven by code"; one subject inside the other -> a Question. A percentage over 100 of a price
                 or invoice -> a Question.
  delay_cap      a rate per day or week, a stated maximum number of days or weeks and a stated cap, all percentages of one base under
                 one heading: rate x periods is not the cap -> a Question (the paper may mean them apart).
  schedules      the order of precedence against the list of Schedules the contract names as its parts: a ranked Schedule not
                 listed, or a listed Schedule not ranked, or one ranked twice -> "Not met, proven by code" (both lists read whole);
                 the listed Schedules the package does not hold -> ONE Question.
  terms          a term the contract defines in quotes ("Work", "COMPANY") used with a different capitalisation that is still
                 capitalised ("Company") -> a Question (never a verdict: the meaning may be the same).
A value left to the vendor (blank, By Contractor, TBA, TBD, *) has no figure and is never compared. Nothing guesses the AI's meaning:
code parses the paper's own words. Pure: no model, no network, no write. Hooked at ONE place: `engine._judge` adds
`checklist_items` and `engine._after_judge` adds `lines` (after every AI step, so no AI step rewrites a code line).
"""

from __future__ import annotations

import calendar
import contextlib
import json
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from .. import contract_checks as CC
from .fail_words import PROVEN_FAIL
from .steps import KNOWLEDGE
from .verify import quote_in

KIND = "contract"
CHECKLIST = (
    Path(__file__).resolve().parent.parent / "reference" / "contract_checklist.json"
)
TOPIC = "contract checked by code"
SOURCE = KNOWLEDGE  # the paper against itself: no held standard is the rule
READ_FROM = "verified quotes"
MAX_QUOTE = 420

IDS = {
    "amount_words": "C1",
    "dates": "C2",
    "splits": "C3",
    "percent_values": "C4",
    "delay_cap": "C5",
    "schedules": "C6",
    "terms": "C7",
}


def is_contract(identity: dict | None) -> bool:
    return str((identity or {}).get("kind") or "").strip().lower() == KIND


# ------------------------------------------------------------------------------------------------ the fixed checklist


@lru_cache(maxsize=1)
def checklist() -> dict:
    return json.loads(CHECKLIST.read_text(encoding="utf-8"))


def checklist_items(identity: dict | None) -> list[dict]:
    """The fixed contract checklist as judge items (same fields as the always-on items), for a contract only; [] otherwise.
    Not from a held standard: the judge's word is an AI opinion or a Question, never Met or Not met."""
    if not is_contract(identity):
        return []
    out = []
    for it in checklist()["items"]:
        check = it["check"]
        if it.get("code_part"):
            check += f" Code already compares: {it['code_part'].split(' (`')[0]}; do not repeat that comparison."
        out.append(
            {
                "id": it["id"],
                "topic": it["topic"],
                "what_to_check": check,
                "book": "",
                "clause": "",
                "page": None,
                "rule_quote": "",
                "applies_when": "the paper is a contract",
                "paper_fields": [],
                "paper_pages": [],
                "kind": "consistency" if it["decided_by"] != "judge" else "presence",
                "source": KNOWLEDGE,
                "stands_in_for": "the fixed contract checklist",
                "always_on": True,
                "context": "",
                "carries": [],
                "named_books": [],
            }
        )
    return out


# ------------------------------------------------------------------------------------------------ shared

_SPACE = re.compile(r"\s+")


def flat(text: str) -> str:
    return _SPACE.sub(" ", str(text or "")).strip()


def _quote(flat_page: str, start: int, end: int) -> str:
    return flat_page[max(0, start) : end].strip(" ,;")


def _line(
    check: str,
    n: int,
    label: str,
    page: int,
    quote: str,
    comment: str,
    field: str,
    compare: dict | None = None,
    note: str = "",
) -> dict:
    return {
        "item_id": IDS[check],
        "finding_no": n,
        "label": label,
        "field": field[:100],
        "page": page,
        "quote": quote,
        "quote_unverified": "",
        "comment": comment[:400],
        "standard": "",
        "clause": "",
        "source": SOURCE,
        "topic": TOPIC,
        "code": "; ".join(x for x in (f"contract code: {check}", note) if x),
        "numbers": None,
        "code_compare": compare,
        "deferred": False,
        "ask": "concern",
    }


def _firm(check, n, page, quote, sentence, field, paper_value, rule_value, why) -> dict:
    return _line(
        check,
        n,
        "Not met",
        page,
        quote,
        f"{PROVEN_FAIL}: {sentence}",
        field,
        {
            "read_from": READ_FROM,
            "result": "fail",
            "operator": "==",
            "paper_value": paper_value,
            "rule_value": rule_value,
            "why": why,
        },
    )


def _question(
    check, n, page, quote, sentence, field, compare: dict | None = None
) -> dict:
    return _line(check, n, "Question", page, quote, sentence, field, compare)


# ------------------------------------------------------------------------------------------------ numbers in words

_UNITS = {
    w: i
    for i, w in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
        ]
    )
}
_TENS = {
    w: 10 * (i + 2)
    for i, w in enumerate(
        ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
    )
}
_SCALES = {"thousand": 10**3, "million": 10**6, "billion": 10**9}
NUMBER_WORDS = set(_UNITS) | set(_TENS) | set(_SCALES) | {"hundred"}


def words_value(words: list[str]) -> int | None:
    """The number of a run of English number words ("one hundred and eighty million"), or None when it is not one number."""
    total, cur, seen = 0, 0, False
    for raw in words:
        w = raw.lower()
        if w == "and":
            continue
        if w in _UNITS:
            cur += _UNITS[w]
        elif w in _TENS:
            cur += _TENS[w]
        elif w == "hundred":
            cur = (cur or 1) * 100
        elif w in _SCALES:
            total += (cur or 1) * _SCALES[w]
            cur = 0
        else:
            return None
        seen = True
    return total + cur if seen else None


#: currency names in words -> ISO code (plain vocabulary of money names, not one paper's)
CURRENCY_NAMES = {
    "united states dollars": "USD",
    "united states dollar": "USD",
    "us dollars": "USD",
    "kuwaiti dinars": "KWD",
    "kuwaiti dinar": "KWD",
    "saudi riyals": "SAR",
    "saudi riyal": "SAR",
    "saudi arabian riyals": "SAR",
    "euros": "EUR",
    "euro": "EUR",
    "pounds sterling": "GBP",
    "british pounds": "GBP",
    "uae dirhams": "AED",
    "emirati dirhams": "AED",
    "qatari riyals": "QAR",
    "omani rials": "OMR",
    "bahraini dinars": "BHD",
    "japanese yen": "JPY",
    "swiss francs": "CHF",
    "indian rupees": "INR",
    "pakistani rupees": "PKR",
    "chinese yuan": "CNY",
}
_BRACKET = re.compile(
    r"\(\s*(?P<code>[A-Z]{3})?\s*(?P<fig>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<pct>%)?\s*\)"
)
_WORD = re.compile(r"[A-Za-z]+")


def _words_before(flat_page: str, at: int) -> tuple[list[str], int] | None:
    """The run of number words that ends right before `at` (spaces, hyphens, 'and' between; 'percent' / 'per cent' dropped at its
    end), with the position it starts at; None when no number word stands there."""
    head = flat_page[:at].rstrip()
    toks = list(re.finditer(r"[A-Za-z]+", head))
    if not toks or toks[-1].end() != len(head):
        return None
    i = len(toks) - 1
    pct = False
    if toks[i].group().lower() == "percent":
        pct, i = True, i - 1
    elif (
        toks[i].group().lower() == "cent"
        and i > 0
        and toks[i - 1].group().lower() == "per"
    ):
        pct, i = True, i - 2
    run = []
    while i >= 0:
        w = toks[i].group().lower()
        gap = head[toks[i].end() : toks[i + 1].start()] if i + 1 < len(toks) else ""
        if run and not re.fullmatch(r"[\s\-]*", gap):
            break
        if w in NUMBER_WORDS or (w == "and" and run):
            run.insert(0, toks[i])
            i -= 1
        else:
            break
    while run and run[0].group().lower() == "and":
        run.pop(0)
    if not run:
        return None
    return [t.group() for t in run] + (["%"] if pct else []), run[0].start()


def check_amount_words(pages: dict[int, str]) -> list[dict]:
    out = []
    for page in sorted(pages):
        fp = flat(pages[page])
        for m in _BRACKET.finditer(fp):
            got = _words_before(fp, m.start())
            if not got:
                continue
            words, start = got
            pct_words = words[-1] == "%"
            if pct_words:
                words = words[:-1]
            said = words_value(words)
            if said is None:
                continue
            fig = float(m.group("fig").replace(",", ""))
            if bool(m.group("pct")) != pct_words and (m.group("pct") or pct_words):
                continue  # "ten (10%)": one side is a percentage, the other not: no verdict
            before = flat(fp[max(0, start - 40) : start]).lower()
            name = next((n for n in CURRENCY_NAMES if before.endswith(n)), None)
            named = CURRENCY_NAMES[name] if name else None
            q_start = (
                start
                - len(fp[max(0, start - 40) : start].rstrip())
                + before.rfind(name)
                if name
                else start
            )
            quote = _quote(fp, q_start, m.end())
            if not quote_in(quote, pages[page]):
                continue
            code = m.group("code")
            what = "percentage" if pct_words else "amount"
            if abs(said - fig) > 1e-9 * max(1.0, fig):
                shown = f"{m.group('fig')}{'%' if m.group('pct') else ''}"
                out.append(
                    _firm(
                        "amount_words", len(out) + 1, page, quote,
                        f"the {what} in words ({' '.join(words)} = {said:,}) is not the {what} in figures ({shown}) on page "
                        f"{page}; state one {what} in both.",
                        f"{what} in words and figures", fig, said, "words and figures of one quote differ",
                    )
                )  # fmt: skip
            elif named and code and named != code:
                out.append(
                    _firm(
                        "amount_words", len(out) + 1, page, quote,
                        f"the currency in words ({named}) is not the currency in figures ({code}) on page {page}; "
                        "state one currency in both.",
                        "currency in words and figures", code, named, "currency of words and figures of one quote differ",
                    )
                )  # fmt: skip
    return out


# ------------------------------------------------------------------------------------------------ dates and durations

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MON = "|".join(sorted((m for m in _MONTHS), key=len, reverse=True))
_DATE = re.compile(
    rf"\b(?:(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?(?P<m1>{_MON})\.?,?\s+(?P<y1>\d{{4}})"
    rf"|(?P<m2>{_MON})\.?\s+(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y2>\d{{4}})"
    rf"|(?P<y3>\d{{4}})-(?P<mo3>\d{{2}})-(?P<d3>\d{{2}}))\b",
    re.I,
)
_START = re.compile(r"\b(commence\w*|start\w*|effective|begin\w*)\b", re.I)
_END = re.compile(
    r"\b(complet\w*|finish\w*|expir\w*|end\s+date|not\s+later\s+than)\b", re.I
)
_DURATION = re.compile(
    r"(?:\b(?P<w>[A-Za-z]+(?:[\s\-][A-Za-z]+){0,3})\s*)?\(?\s*(?P<n>\d{1,4})\s*\)?\s*(?:calendar\s+)?"
    r"(?P<unit>months?|weeks?|days?|years?)\b",
    re.I,
)
SENTENCE_GAP = re.compile(r"(?<=[a-z0-9\)])\.\s+(?=[A-Z])")


def _as_date(m: re.Match) -> date | None:
    try:
        if m.group("y1"):
            return date(
                int(m.group("y1")), _MONTHS[m.group("m1").lower()], int(m.group("d1"))
            )
        if m.group("y2"):
            return date(
                int(m.group("y2")), _MONTHS[m.group("m2").lower()], int(m.group("d2"))
            )
        return date(int(m.group("y3")), int(m.group("mo3")), int(m.group("d3")))
    except (ValueError, KeyError):
        return None


def _add(start: date, n: int, unit: str) -> date:
    unit = unit.lower().rstrip("s")
    if unit == "day":
        return start + timedelta(days=n)
    if unit == "week":
        return start + timedelta(weeks=n)
    months = n * (12 if unit == "year" else 1)
    y, mo = divmod(start.month - 1 + months, 12)
    y += start.year
    d = min(start.day, calendar.monthrange(y, mo + 1)[1])
    return date(y, mo + 1, d)


def _role(fp: str, m: re.Match) -> str | None:
    """'start' / 'end' from the date's own defined name in the bracket right after it ('(herein referred to as the "X
    Completion Date")'), else from the start/end word nearest before it."""
    after = re.match(r"\s*\((?P<inside>[^()]{0,80})\)?", fp[m.end() : m.end() + 90])
    if after:
        s, e = _START.search(after.group("inside")), _END.search(after.group("inside"))
        if bool(s) != bool(e):
            return "start" if s else "end"
    before = fp[max(0, m.start() - 45) : m.start()]
    hits = [(x.end(), "start") for x in _START.finditer(before)] + [
        (x.end(), "end") for x in _END.finditer(before)
    ]
    return max(hits)[1] if hits else None


def _sentences(fp: str) -> list[tuple[int, int]]:
    out, at = [], 0
    for m in SENTENCE_GAP.finditer(fp):
        out.append((at, m.start() + 1))
        at = m.end()
    out.append((at, len(fp)))
    return out


def check_dates(pages: dict[int, str]) -> list[dict]:
    out = []
    for page in sorted(pages):
        fp = flat(pages[page])
        for s0, s1 in _sentences(fp):
            found = [(m, _as_date(m), _role(fp, m)) for m in _DATE.finditer(fp, s0, s1)]
            starts = [(m, d) for m, d, r in found if d and r == "start"]
            ends = [(m, d) for m, d, r in found if d and r == "end"]
            if len(starts) != 1 or len(ends) != 1:
                continue  # none, or more than one of a role: code does not choose
            (ms, ds), (me, de) = starts[0], ends[0]
            lo, hi = min(ms.start(), me.start()), max(ms.end(), me.end())
            between = fp[lo:hi]
            durs = [
                d
                for d in _DURATION.finditer(between)
                if not _DATE.search(between, d.start(), d.end())
            ]
            tail = fp[hi : min(s1, hi + 70)]
            quote = _quote(
                fp,
                lo,
                hi
                + (len(tail) - len(tail.lstrip()))
                + len(re.match(r"[^.;]*", tail.lstrip()).group()),
            )
            if len(quote) > MAX_QUOTE:
                quote = _quote(fp, lo, hi)
            if len(quote) > MAX_QUOTE or not quote_in(quote, pages[page]):
                continue
            if de < ds:
                out.append(
                    _firm(
                        "dates", len(out) + 1, page, quote,
                        f"the end date ({de:%d %B %Y}) is before the start date ({ds:%d %B %Y}) on page {page}; correct the dates.",
                        "start and end dates", de.isoformat(), ds.isoformat(), "end before start",
                    )
                )  # fmt: skip
                continue
            if len(durs) != 1:
                continue
            d = durs[0]
            n = int(d.group("n"))
            if d.group("w"):
                ws = [w for w in re.split(r"[\s\-]+", d.group("w")) if w]
                tail_words = []
                for w in reversed(ws):
                    if w.lower() in NUMBER_WORDS or w.lower() == "and":
                        tail_words.insert(0, w)
                    else:
                        break
                said = words_value(tail_words) if tail_words else None
                if said is not None and said != n:
                    continue  # words and figures of the duration differ: `amount_words` says so; no date verdict on it
            expected = _add(ds, n, d.group("unit"))
            slack = 1 if d.group("unit").lower().startswith(("day", "week")) else 3
            if abs((de - expected).days) > slack:
                out.append(
                    _firm(
                        "dates", len(out) + 1, page, quote,
                        f"the start date {ds:%d %B %Y} plus the stated {n} {d.group('unit').lower()} gives {expected:%d %B %Y}, "
                        f"not the stated end date {de:%d %B %Y} (page {page}); make the duration and the dates agree.",
                        "duration against start and end dates", de.isoformat(), expected.isoformat(),
                        "start plus duration is not the end",
                    )
                )  # fmt: skip
    return out


# ------------------------------------------------------------------------------------------------ percentages

_SPLIT = re.compile(
    r"\((?P<body>\s*\d+(?:\.\d+)?\s*%[^()%/]{0,30}(?:/\s*\d+(?:\.\d+)?\s*%[^()%/]{0,30}){1,5})\)"
)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def check_splits(pages: dict[int, str]) -> list[dict]:
    out = []
    for page in sorted(pages):
        fp = flat(pages[page])
        sents = _sentences(fp)
        for m in _SPLIT.finditer(fp):
            parts = [float(x) for x in _PCT.findall(m.group("body"))]
            s0, s1 = next(
                ((a, b) for a, b in sents if a <= m.start() < b), (m.start(), m.end())
            )
            sentence = fp[s0:s1]
            near = fp[max(s0, m.start() - 60) : min(s1, m.end() + 60)]
            eq = re.search(r"\bequal(?:ly)?\b", near, re.I)
            lo = (
                min(m.start(), eq.start() + max(s0, m.start() - 60))
                if eq
                else m.start()
            )
            hi = max(m.end(), eq.end() + max(s0, m.start() - 60)) if eq else m.end()
            quote = _quote(fp, lo, hi)
            if not quote_in(quote, pages[page]):
                continue
            shown = " / ".join(f"{p:g}%" for p in parts)
            if eq and len(set(parts)) > 1:
                out.append(
                    _firm(
                        "splits", len(out) + 1, page, quote,
                        f"the text says '{eq.group(0)}' but the split it gives is {shown} (page {page}); make the words and the "
                        "split agree.",
                        "equal split", shown, "equal parts", "an equal split with unequal parts",
                    )
                )  # fmt: skip
            elif abs(sum(parts) - 100) > 1e-6 and "/" in sentence:
                out.append(
                    _question(
                        "splits", len(out) + 1, page, quote,
                        f"The split {shown} on page {page} adds up to {sum(parts):g}%, not 100%; please confirm the parts.",
                        "split of percentages",
                    )
                )  # fmt: skip
    return out


_CAP = re.compile(
    r"\b(?:shall\s+not\s+exceed|not\s+(?:to\s+)?exceed|not\s+more\s+than|maximum\s+of|limited\s+to|capped\s+at|up\s+to)\b",
    re.I,
)
_RATE = re.compile(
    r"\b(?:equal\s+to|equivalent\s+to|amount\s+of|rate\s+of|at\s+the\s+rate\s+of)\b",
    re.I,
)
_PCT_WORDS = re.compile(
    r"(?:(?:[A-Za-z]+[\s\-]+){0,4}(?:percent|per\s+cent)\s*)?\(?\s*(?P<v>\d+(?:\.\d+)?)\s*%\s*\)?",
    re.I,
)
_HEADING = re.compile(
    r"^\s*(?P<no>\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+(?P<title>[A-Za-z][^.:;]{0,60})$"
)
_STOP = {"the", "a", "an", "of", "to", "and", "or", "any", "its", "this", "that", "such", "for", "in", "on", "by", "be",
         "shall", "will", "may", "is", "are", "total", "amount", "value", "sum", "however", "notwithstanding", "moreover",
         "also", "provided", "further", "therefore", "thereof", "hereof", "hereunder"}  # fmt: skip
_PER = re.compile(r"\bper\s+(?P<unit>day|week|calendar\s+day)\b", re.I)


def _content(text: str) -> tuple[str, ...]:
    return tuple(w for w in (x.lower() for x in _WORD.findall(text)) if w not in _STOP and w not in NUMBER_WORDS
                 and w not in ("percent", "per", "cent"))  # fmt: skip


def _heading_at(pages: dict[int, str]) -> dict[tuple[int, int], str]:
    """(page, line index) -> the nearest clause heading above it ('6.1 retention'), across pages."""
    out, cur = {}, ""
    for page in sorted(pages):
        lines = [ln.strip() for ln in pages[page].splitlines()]
        for i, ln in enumerate(lines):
            m = _HEADING.match(ln)
            if m and len(m.group("title").split()) <= 8:
                cur = f"{m.group('no')} {m.group('title').strip().lower()}"
            out[(page, i)] = cur
    return out


def percent_statements(pages: dict[int, str]) -> list[dict]:
    """Every percentage stated as a cap or a rate of a base ('... shall not exceed three percent (3%) of the <base>'), with its
    clause heading, its subject words (before the verb), its base words (after 'of') and a quote that verifies on its page."""
    heads = _heading_at(pages)
    out = []
    for page in sorted(pages):
        raw_lines = pages[page].splitlines()
        offsets, at = [], 0
        for ln in raw_lines:
            offsets.append(at)
            at += len(ln) + 1
        fp_raw = pages[page]
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%", fp_raw):
            li = max(i for i, o in enumerate(offsets) if o <= m.start())
            head = heads.get((page, li), "")
            pre = fp_raw[max(0, m.start() - 220) : m.start()]
            post = fp_raw[m.end() : m.end() + 200]
            verb = None
            for rx, kind in ((_CAP, "cap"), (_RATE, "rate")):
                hits = list(rx.finditer(pre))
                if hits and len(flat(pre[hits[-1].end() :])) <= 40:
                    verb = (kind, hits[-1])
                    break
            if not verb:
                continue
            kind, vm = verb
            of = re.match(
                r"\s*\)?\s*(?:[A-Za-z]+\s+){0,2}?of\s+(?:the\s+)?(?P<base>[^.,;()]{3,80})",
                post,
            )
            if not of:
                continue
            base_text = flat(of.group("base"))
            base = _content(
                re.split(
                    r"\b(?:to\s+be|under|pursuant|which|that|shall|after|before|set\s+out|as\s+per|in\s+accordance|specified|stated|per|for)\b",
                    base_text,
                )[0]
            )
            if not base:
                continue
            head_text = re.split(r"[.;:]", pre[: vm.start()])[-1]
            toks = list(re.finditer(r"\S+", head_text))
            subject = _content(" ".join(t.group() for t in toks[-5:]))
            q_from = (
                (vm.start() - len(head_text) + toks[-3:][0].start())
                if toks
                else vm.start()
            )
            quote = flat(
                pre[q_from:] + fp_raw[m.start() : m.end()] + post[: of.end("base")]
            ).strip(" ,;")
            if not quote_in(quote, fp_raw):
                continue
            per = _PER.search(flat(post[:80]))
            out.append(
                {
                    "page": page,
                    "value": float(m.group(1)),
                    "kind": kind,
                    "head": head,
                    "subject": subject,
                    "base": base[-2:],
                    "per": per.group("unit").split()[-1].lower() if per else "",
                    "quote": quote,
                }
            )
    return out


def check_percent_values(pages: dict[int, str]) -> list[dict]:
    st = percent_statements(pages)
    out, seen = [], set()
    for i, a in enumerate(st):
        if a["value"] > 100 and a["kind"] in ("cap", "rate") and not a["per"]:
            out.append(
                _question(
                    "percent_values", len(out) + 1, a["page"], a["quote"],
                    f"A percentage of {a['value']:g}% of the {' '.join(a['base'])} is stated on page {a['page']}; "
                    "please confirm it, a share above 100% is more than the whole.",
                    "percentage over 100",
                )
            )  # fmt: skip
        for b in st[i + 1 :]:
            if (
                not a["head"]
                or a["head"] != b["head"]
                or a["kind"] != b["kind"]
                or a["base"] != b["base"]
            ):
                continue
            if a["per"] != b["per"] or a["value"] == b["value"]:
                continue
            key = (a["head"], a["kind"], a["base"], a["per"])
            if key in seen:
                continue
            same = a["subject"] == b["subject"] and a["subject"]
            seen.add(key)
            what = "cap" if a["kind"] == "cap" else "rate"
            sentence = (
                f"clause {a['head'].split(' ')[0]} states two different {what}s on '{' '.join(a['base'])}': "
                f"{a['value']:g}% on page {a['page']} and {b['value']:g}% on page {b['page']} ('{b['quote'][:120]}')"
            )
            if same:
                out.append(
                    _firm(
                        "percent_values", len(out) + 1, a["page"], a["quote"], sentence + "; state one value.",
                        f"two values of one {what}", a["value"], b["value"], "two different values for the same item",
                    )
                )  # fmt: skip
            else:
                out.append(
                    _question(
                        "percent_values", len(out) + 1, a["page"], a["quote"],
                        "C" + sentence[1:] + "; please confirm which value applies.",
                        f"two values of one {what}",
                        {"read_from": READ_FROM, "result": "cannot", "why": "same clause, base and kind; the subjects differ: not proven the same item",
                         "paper_value": a["value"], "rule_value": b["value"]},
                    )
                )  # fmt: skip
    return out


_MAX_PERIODS = re.compile(
    r"\bmaximum\s+(?:period\s+)?of\s+(?:[A-Za-z\-\s]{0,30})?\(?\s*(?P<n>\d{1,4})\s*\)?\s*(?:calendar\s+)?(?P<unit>days?|weeks?)\b",
    re.I,
)


def check_delay_cap(pages: dict[int, str]) -> list[dict]:
    st = percent_statements(pages)
    heads = _heading_at(pages)
    out = []
    by_head: dict[str, list[dict]] = {}
    for s in st:
        if s["head"]:
            by_head.setdefault(s["head"], []).append(s)
    for head, group in by_head.items():
        rates = [s for s in group if s["per"]]
        caps = [s for s in group if s["kind"] == "cap" and not s["per"]]
        if len(rates) != 1 or len(caps) != 1 or rates[0]["base"] != caps[0]["base"]:
            continue
        r, c = rates[0], caps[0]
        maxima = []
        for page in sorted(pages):
            for i, ln in enumerate(pages[page].splitlines()):
                if heads.get((page, i)) != head:
                    continue
                for m in _MAX_PERIODS.finditer(ln):
                    if m.group("unit").lower().rstrip("s") == r["per"]:
                        maxima.append((page, int(m.group("n")), flat(m.group(0))))
        if len(maxima) != 1:
            continue
        page, n, q = maxima[0]
        if abs(r["value"] * n - c["value"]) > 1e-6 and quote_in(q, pages[page]):
            out.append(
                _question(
                    "delay_cap", len(out) + 1, r["page"], r["quote"],
                    f"The rate {r['value']:g}% per {r['per']} for the stated maximum of {n} {r['per']}s gives "
                    f"{r['value'] * n:g}%, but the stated cap is {c['value']:g}% (page {c['page']}); please confirm which applies.",
                    "delay damages rate and cap",
                )
            )  # fmt: skip
    return out


# ------------------------------------------------------------------------------------------------ schedules


#: a line of this many words or more between two Schedule lines is a body sentence: the list ended (a title or a page header is shorter)
LIST_BREAK_WORDS = 10


def _schedule_list(pages: dict[int, str]) -> list[tuple[str, int, str]]:
    """The Schedules the contract lists as its parts: (label, page, the line) of every line that STARTS with a Schedule label and is
    not an item of a numbered list (its line, or the line before it, is not a list number), in the longest run of three or more
    such lines with no body sentence (LIST_BREAK_WORDS words or more) between them."""
    lines = CC.lines_of(sorted(pages.items()))
    runs, cur = [], []
    for i, (page, ln) in enumerate(lines):
        part = CC._heading_part(ln)
        if not part or part[0][0] != "schedule":
            if cur and len(_WORD.findall(ln)) >= LIST_BREAK_WORDS:
                runs.append(cur)
                cur = []
            continue
        prev = lines[i - 1][1] if i else ""
        if re.fullmatch(r"\d{1,2}\.", prev.strip()) or re.match(r"^\d{1,2}\.\s", ln):
            continue  # an item of the order of precedence (a numbered list)
        cur.append((part[0][1], page, ln))
    if cur:
        runs.append(cur)
    best = max(runs, key=len) if runs else []
    return best if len(best) >= 3 else []


def _rank_line(pages: dict[int, str], page: int, label: str) -> str:
    for ln in pages.get(page, "").splitlines():
        found = CC.labels(ln)
        if found and found[0][0] == "schedule" and found[0][1] == label:
            return flat(ln)
    return ""


def check_schedules(pages: dict[int, str], held: set[str] | None = None) -> list[dict]:
    """The order of precedence against the list of Schedules (both read whole), and the listed Schedules against the package.
    `held`: the labels of the Schedules the package holds and a recorded link ties to the paper; None = not known (no line)."""
    ranks = [
        (r, k, p)
        for r, k, p in CC.precedence_list(sorted(pages.items()))
        if k[0] == "schedule"
    ]
    listed = _schedule_list(pages)
    out = []
    if len(ranks) >= 3 and len(listed) >= 3:
        names = {lab for lab, _p, _l in listed}
        ranked: dict[str, list[tuple[int, int]]] = {}
        for r, (_w, lab), p in ranks:
            ranked.setdefault(lab, []).append((r, p))
        for lab, places in ranked.items():
            q = _rank_line(pages, places[0][1], lab)
            if not q or not quote_in(q, pages[places[0][1]]):
                continue
            if lab not in names:
                out.append(
                    _firm(
                        "schedules", len(out) + 1, places[0][1], q,
                        f"Schedule {lab} is ranked {places[0][0]} in the order of precedence (page {places[0][1]}) but is not "
                        f"among the Schedules the contract lists as its parts ({', '.join(sorted(names))}); add it to the list "
                        "or remove it from the order.",
                        "order of precedence against the list of Schedules", f"Schedule {lab}", "listed Schedules",
                        "a ranked Schedule is not listed",
                    )
                )  # fmt: skip
            if len(places) > 1:
                out.append(
                    _firm(
                        "schedules", len(out) + 1, places[0][1], q,
                        f"Schedule {lab} is ranked more than once in the order of precedence (ranks "
                        f"{', '.join(str(r) for r, _p in places)}); rank it once.",
                        "order of precedence", f"ranks {[r for r, _p in places]}", "one rank", "a Schedule ranked twice",
                    )
                )  # fmt: skip
        for lab, page, ln in listed:
            q = flat(ln)
            if lab in ranked or not quote_in(q, pages[page]):
                continue
            out.append(
                _firm(
                    "schedules", len(out) + 1, page, q,
                    f"Schedule {lab} is listed as a part of the contract (page {page}) but has no rank in the order of "
                    "precedence; give it a rank.",
                    "list of Schedules against the order of precedence", f"Schedule {lab}", "ranked Schedules",
                    "a listed Schedule is not ranked",
                )
            )  # fmt: skip
    if held is not None and listed:
        missing = [(lab, page, ln) for lab, page, ln in listed if lab not in held]
        if missing:
            lab, page, ln = missing[0]
            q = flat(ln)
            if quote_in(q, pages[page]):
                out.append(
                    _question(
                        "schedules", len(out) + 1, page, q,
                        f"Schedules {', '.join(m[0] for m in missing)} are named as parts of the contract but are not held in "
                        "this contract package, so they could not be checked; please provide them.",
                        "listed Schedules held in the package",
                    )
                )  # fmt: skip
    return out


# ------------------------------------------------------------------------------------------------ defined terms

_DEF = re.compile(
    r"(?:referred\s+to\s+(?:collectively\s+|individually\s+)?as\s+(?:the\s+)?|\(\s*(?:the\s+)?|\bor\s+)"
    r"[\"“](?P<term>[A-Z][A-Za-z\-]*(?:\s+[A-Z][A-Za-z\-]*){0,4})[\"”]"
)


def defined_terms(pages: dict[int, str]) -> dict[str, tuple[int, str]]:
    """{term as defined: (page, quote)} for every capitalised term the paper defines in quotes after 'referred to as' or an
    opening bracket ('(the "Work")', '"Work" or "WORK"')."""
    out: dict[str, tuple[int, str]] = {}
    for page in sorted(pages):
        fp = flat(pages[page])
        for m in _DEF.finditer(fp):
            term = m.group("term").strip()
            if len(term) < 3:
                continue
            out.setdefault(term, (page, _quote(fp, m.start(), m.end())))
    return out


def check_terms(pages: dict[int, str]) -> list[dict]:
    """ONE Question for the paper: each defined term written in another capitalised form, with its count; the quote and page are
    those of the first such use. Never a verdict (the meaning may be the same)."""
    terms = defined_terms(pages)
    forms: dict[str, set[str]] = {}
    for t in terms:
        forms.setdefault(t.casefold(), set()).add(t)
    found = []  # (page, at, used, flat page, allowed forms, count)
    for low, allowed in forms.items():
        rx = re.compile(
            r"(?<![A-Za-z])"
            + r"\s+".join(re.escape(w) for w in low.split())
            + r"(?![A-Za-z])",
            re.I,
        )
        odd: list[tuple[int, int, str, str]] = []
        for page in sorted(pages):
            fp = flat(pages[page])
            for m in rx.finditer(fp):
                used = " ".join(m.group(0).split())
                if used in allowed or not used[0].isupper() or used.islower():
                    continue
                if m.start() > 0 and fp[m.start() - 1] in '"\u201c':
                    continue  # a definition or a quoted mention
                odd.append((page, m.start(), used, fp))
        if odd:
            found.append((*odd[0], allowed, len(odd)))
    for page, at, used, fp, _allowed, _n in found:
        quote = _quote(fp, max(0, at - 40), at + len(used) + 30)
        quote = quote[quote.find(" ") + 1 :] if at >= 40 else quote
        if quote_in(quote, pages[page]):
            break
    else:
        return []
    said = "; ".join(
        f"{' / '.join(sorted(al))} written '{u}' {n} time(s) (first on page {p})"
        for p, _a, u, _f, al, n in found
    )
    return [
        _question(
            "terms", 1, page, quote,
            f"Defined terms are written in other forms: {said}; please use the defined form or confirm the same meaning.",
            "defined terms used in another form",
        )
    ]  # fmt: skip


# ------------------------------------------------------------------------------------------------ all


def lines(
    pages: dict[int, str], identity: dict | None, held: set[str] | None = None
) -> list[dict]:
    """Every code line of a contract, in check order; [] for any other kind. A check that fails on a paper adds no line and
    never stops the review."""
    if not is_contract(identity):
        return []
    out: list[dict] = []
    for fn in (
        check_amount_words,
        check_dates,
        check_splits,
        check_percent_values,
        check_delay_cap,
        check_terms,
    ):
        try:
            out += fn(pages)
        except Exception:  # noqa: BLE001 - a parse fault of one check never stops the review
            continue
    with contextlib.suppress(Exception):  # a parse fault never stops the review
        out += check_schedules(pages, held)
    return out


def held_labels(
    conn, paper_id: str, shown: frozenset[str] = frozenset()
) -> set[str] | None:
    """The labels of the Schedules the package holds and a recorded link ties to the paper (`references.held_schedules`)."""
    try:
        from .references import held_schedules

        linked, _other = held_schedules(conn, paper_id, shown)
        return {lab for (w, lab) in linked if w == "schedule"}
    except Exception:  # noqa: BLE001 - not known: no package line
        return None


def add_lines(conn, state, paper, allowed_books=frozenset()) -> int:
    """THE hook (`engine._after_judge`, last): the contract's code lines appended to the decided lines. Returns how many."""
    new = lines(
        paper.pages,
        state.identity,
        held_labels(conn, state.paper_id, frozenset(allowed_books)),
    )
    state.decided.extend(new)
    return len(new)
