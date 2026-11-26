"""THE FORMULA CHECK LIBRARY (order 14, planner 25 Nov 2026, item 3): points the paper itself decides, by code.

A limit that a HELD standard states in words and numbers is checked against two values the paper states, both read by code from the
paper's own rows (so each is a verified quote, never an AI's number), with the app's unit code (`verify.compare`). A check fires only
when (1) both values are on the same page, each label standing once on it, (2) neither is left open (By Contractor with no figure,
TBA, TBD, *: such a value is a Question, never Met or Not met), (3) the clause's own sentence is found, by regex, on a page of a rule
book THIS review carried (the clause is in a held book), and (4) the units are comparable (a gauge value is never set against an
unmarked one). The line it makes goes through the ordinary path: label Met / Not met with a comparison of `read_from` "verified
quotes", so the existing firm-finding rule (`fail_words.proven_fail`) says "Not met, proven by code" and nothing new is shown.

Each check names its clause. A check proves only what the clause proves: the hydrotest check can show a test pressure BELOW the clause's
minimum, never that a test pressure is enough (the clause multiplies by a stress ratio the paper does not state).
No model, no network, no write.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import PROVISIONAL  # noqa: F401 - re-exported with the label words (one home)
from .fail_words import PROVEN_FAIL

log = logging.getLogger(__name__)
PATH = Path(__file__).resolve().parent.parent / "reference" / "formula_checks.json"
#: Rows are cells apart by two or more spaces (the paper's visual reading order keeps a row's columns on one line).
_CELLS = re.compile(r"\s{2,}")
_NOTE = re.compile(
    r"\b(?:by\s+(?:contractor|vendor|supplier|manufacturer)|as\s+per|tba|tbd|tbc)\b",
    re.IGNORECASE,
)
_PART = re.compile(
    r"^(?P<lo>-?\d+(?:\.\d+)?)(?:\s*(?:to|-|\u2013)\s*(?P<hi>-?\d+(?:\.\d+)?))?\s*(?P<unit>[°º]?(?!to\b|and\b|or\b)[A-Za-z]{1,5})?$"
)

LABELS = {
    "design_operating_pressure": r"design\s*/\s*operating\s+pressure",
    "design_operating_temperature": r"design\s*/\s*operating\s+temperature",
    "design_pressure": r"(?:internal\s+)?design\s+pressure",
    "operating_pressure": r"operating\s+pressure",
    "max_operating_pressure": r"max(?:imum|\.)?\s+operating\s+pressure",
    "design_temperature": r"(?:internal\s+)?(?:max(?:imum|\.)?\s+)?design\s+temperature",
    "operating_temperature": r"operating\s+temperature",
    "max_operating_temperature": r"max(?:imum|\.)?\s+operating\s+temperature",
    "mawp": r"(?:max\.?|maximum)\s*allow(?:\.|able)?\s*working\s+pressure|mawp",
    "set_pressure": r"set\s+pressure",
    "test_pressure": r"hydro(?:static)?[\s-]*test\s+pressure",  # only a label that says hydro: a seat, leak or pneumatic test is another test
}
_BARE = re.compile(r"-?\d+(?:\.\d+)?")
_UNIT_CELL = re.compile(
    r"[\u00b0\u00ba]?[A-Za-z]{1,5}(?:\s*\((?:ga|g|a)\))?", re.IGNORECASE
)
_LABEL_RX = {k: re.compile(v + r"\s*:?", re.IGNORECASE) for k, v in LABELS.items()}


@dataclass(frozen=True)
class Val:
    low: float
    high: float
    unit: str


@dataclass
class Field:
    key: str
    page: int
    quote: str
    vals: list  # [Val | None]: "-" is no value


def _unit(raw: str | None) -> str:
    u = re.sub(r"[°º]", "", str(raw or "")).strip()
    return (
        "C" if re.fullmatch(r"[Oo]?C", u) else "F" if re.fullmatch(r"[Oo]?F", u) else u
    )


def parse_value(cell: str) -> list | None:
    """The numbers of a value cell: "9 / 7.5 barg (Note 3)" -> [9 barg, 7.5 barg]; "-5 to 90OC / 60OC" -> [-5..90 C, 60 C].
    A unit written once at the end serves the numbers before it. None when the cell leaves the value open (no figure) or is not a
    plain number list: never a guess."""
    text = re.sub(
        r"\s*\((ga|g)\)", "g", str(cell or ""), flags=re.IGNORECASE
    )  # "bar (ga)" is gauge: kept, never lost with the notes
    text = re.sub(r"\s*\(a\)", "a", text)
    text = re.sub(r"\([^)]*\)", " ", text)
    cut = _NOTE.search(text)
    core = (text[: cut.start()] if cut else text).strip(" /")
    if not re.search(r"\d", core):
        return None
    parts = [p.strip() for p in core.split("/")]
    out: list = []
    for p in parts:
        if p in ("-", "\u2013", "NA", "N/A"):
            out.append(None)
            continue
        m = _PART.match(p)
        if not m:
            return None
        lo = float(m["lo"])
        out.append(Val(lo, float(m["hi"]) if m["hi"] else lo, _unit(m["unit"])))
    last = ""
    for i in range(
        len(out) - 1, -1, -1
    ):  # a unit written once serves the numbers before it
        v = out[i]
        if v is None:
            continue
        last = v.unit or last
        out[i] = Val(v.low, v.high, v.unit or last)
    return out if any(out) and all(v is None or v.unit for v in out) else None


def read_fields(pages: dict[int, str]) -> dict[int, dict[str, list[Field]]]:
    """{page: {label key: [Field]}} read from each row's cells: a label cell, then the value cell beside it."""
    found: dict[int, dict[str, list[Field]]] = {}
    for page, text in pages.items():
        for line in str(text or "").splitlines():
            cells = [c.strip() for c in _CELLS.split(line.strip()) if c.strip()]
            for i, cell in enumerate(cells[:-1]):
                for key, rx in _LABEL_RX.items():
                    if not rx.fullmatch(cell):
                        continue
                    value = cells[i + 1]
                    if (
                        _BARE.fullmatch(value)
                        and i + 2 < len(cells)
                        and _UNIT_CELL.fullmatch(cells[i + 2])
                        and not any(_BARE.fullmatch(c) for c in cells[i + 3 :])
                    ):  # a further number cell on the row (an item or note column): which cell is the value is a guess, so none is read
                        value = f"{value} {cells[i + 2]}"  # the value and its unit stand in two cells
                    if vals := parse_value(value):
                        found.setdefault(page, {}).setdefault(key, []).append(
                            Field(key, page, f"{cell}  {value}", vals)
                        )
    return found


def _once(fields: dict[str, list[Field]], key: str) -> Field | None:
    got = fields.get(key) or []
    return (
        got[0] if len(got) == 1 else None
    )  # a label that stands twice on a page is not guessed between


# ------------------------------------------------------------------ the clause probes (the clause is in a held book)


@dataclass(frozen=True)
class Probe:
    ref: str  # the clause as the book numbers it
    rx: str  # the clause's own sentence, found on a page of a carried book (whitespace and hyphen breaks folded)


@dataclass(frozen=True)
class Hit:
    book: str
    standard: str
    page: int
    factor: float | None


def _fold(text: str) -> str:
    return " ".join(re.sub(r"(\w)- (\w)", r"\1\2", str(text or "")).split())


def find_clause(
    books: dict[str, tuple[str, dict[int, str]]], probe: Probe
) -> Hit | None:
    """The first carried book whose page holds the clause's sentence: (book id, its identifier, page, the factor the sentence states)."""
    rx = re.compile(probe.rx, re.IGNORECASE)
    for book, (identifier, pages) in books.items():
        for page in sorted(pages):
            m = rx.search(_fold(pages[page]))
            if m:
                factor = (
                    float(m.group("factor"))
                    if "factor" in rx.groupindex and m.group("factor")
                    else None
                )
                return Hit(book, identifier, page, factor)
    return None


# ------------------------------------------------------------------ the checks


@dataclass(frozen=True)
class Rule:
    """`left <op> k * right` proves a verdict. `k` is a number, or "factor" / "percent": the number the clause's own sentence states."""

    op: str
    k: float | str = 1.0


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    probe: Probe
    left: tuple  # the label keys of the first value, the best first (a combined row also serves design/operating)
    right: tuple  # the label keys of the second value, the best first
    met: (
        Rule | None
    )  # when it holds, the check proves Met (None: this check never proves Met)
    not_met: Rule  # when it holds, the check proves Not met
    words: str  # the plain sentence, "{a}" the left value, "{b}" the right, "{rel}" how they relate, "{f}" the clause's factor


@lru_cache(maxsize=1)
def _checks(mtime: float) -> tuple:  # noqa: ARG001 - the argument is the cache key (re-read when the file changes)
    data = json.loads(PATH.read_text(encoding="utf-8"))
    out = []
    for c in data["checks"]:
        rule = lambda r: Rule(r[0], r[1]) if r else None  # noqa: E731
        out.append(Check(c["id"], c["title"], Probe(c["ref"], c["probe"]), tuple(c["left"]), tuple(c["right"]),
                         rule(c["met"]), rule(c["not_met"]), c["words"]))  # fmt: skip
    return tuple(out)


def checks() -> tuple:
    """The checks of `reference/formula_checks.json` (re-read when the file changes); () when it cannot be read."""
    try:
        return _checks(PATH.stat().st_mtime)
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        log.info("formula checks not read (%s)", type(exc).__name__)
        _fault("the table of checks could not be read (" + type(exc).__name__ + ")")
        return ()


_REL = {">=": "not below", "<": "below", "<=": "not above", ">": "above"}


def _operands(check: Check, fields: dict[str, list[Field]]):
    """(left Field, left Val, right Field, right Val) for a check on one page, or None. A combined row ("Design/Operating pressure
    9 / 7 barg") supplies both values; separate rows supply one each."""
    combo = {"design_pressure": "design_operating_pressure", "operating_pressure": "design_operating_pressure",
             "design_temperature": "design_operating_temperature", "operating_temperature": "design_operating_temperature"}  # fmt: skip
    pick = {
        "design_pressure": 0,
        "operating_pressure": 1,
        "design_temperature": 0,
        "operating_temperature": 1,
    }

    def one(keys: tuple):
        for key in keys:
            direct = _once(fields, key)
            if direct is not None:
                if len(direct.vals) != 1 or direct.vals[0] is None:
                    return None  # two values in one cell ("-20 / 200 C"), or a dash: which one is meant is a guess, so no line
                return direct, direct.vals[0]
        for key in keys:
            shared = _once(fields, combo.get(key, ""))
            if (
                shared is not None
                and len(shared.vals) == 2
                and shared.vals[pick[key]] is not None
            ):
                return shared, shared.vals[pick[key]]
        return None

    a, b = one(check.left), one(check.right)
    return (a[0], a[1], b[0], b[1]) if a and b else None


def _k(rule: Rule, factor: float | None) -> float | None:
    if rule.k == "factor":
        return factor
    if rule.k == "percent":
        return factor / 100.0 if factor else None
    return float(rule.k)


def _decide(
    check: Check, a: Val, b: Val, factor: float | None
) -> tuple[str, dict] | None:
    """("Met"|"Not met", comparison) or None when this check proves nothing for these values (units not comparable, or the values
    lie where the clause says nothing). A range is judged at its upper end ("-3 to 121 C" is covered up to 121)."""
    from .verify import compare

    for rule, word in ((check.met, "Met"), (check.not_met, "Not met")):
        k = _k(rule, factor) if rule else None
        if rule is None or k is None:
            continue
        got = compare(str(a.high), a.unit, rule.op, str(round(b.high * k, 9)), b.unit)
        if got.get("result") == "cannot":
            return None
        if got["result"] == "pass":
            return word, {**got, "op": rule.op, "factor": k}
    return None


def _comparable(ua: str, ub: str) -> bool:
    """A gauge value is never set against an unmarked one, nor an absolute against a gauge (no atmospheric pressure is guessed)."""
    if ua == ub:
        return True

    def kind(u: str) -> str:
        return (
            "g" if u.lower().endswith("g") else "a" if u.lower().endswith("a") else ""
        )

    return bool(kind(ua)) and kind(ua) == kind(ub)


def _sentence(
    check: Check,
    label: str,
    a: Field,
    av: Val,
    b: Field,
    bv: Val,
    hit: Hit,
    factor: float | None,
) -> str:
    if label != "Not met":
        return ""  # a Met is a point that decided itself: no comment
    rel = _REL[check.not_met.op]
    base = check.words.format(
        a=f"{_n(av.high)} {av.unit}",
        b=f"{_n(bv.high)} {bv.unit}",
        rel=rel,
        f=_n(factor or 1.0),
    )
    quotes = [_one_line(a.quote)] + ([] if b.quote == a.quote else [_one_line(b.quote)])
    where = "; ".join(
        f'"{q}" (page {f.page})' for q, f in zip(quotes, (a, b), strict=False)
    )
    return f"{PROVEN_FAIL}: {base} [{where}]; {hit.standard} clause {check.probe.ref} says so. Revise it to meet the rule."


def _one_line(text: str) -> str:
    return " ".join(str(text or "").split())


def _n(v: float) -> str:
    return f"{v:f}".rstrip("0").rstrip(".")


def lines(conn, paper, book_ids) -> list[dict]:
    """The decided lines the formula checks make for this paper, from the rule books the run carried (`book_ids`). [] when no check fires."""
    books = _carried(conn, book_ids)
    if not books:
        return []
    per_page = read_fields(paper.pages)
    out: list[dict] = []
    failed = 0
    for check in checks():
        hit = find_clause(books, check.probe)
        if hit is None:
            continue  # the clause is not in a held book of this review: nothing is checked on its authority
        for page in sorted(per_page):
            try:
                ops = _operands(check, per_page[page])
                if ops is None or not _comparable(ops[1].unit, ops[3].unit):
                    continue
                a, av, b, bv = ops
                decided = _decide(check, av, bv, hit.factor)
                if decided is None:
                    continue
                out.append(_line(check, decided, a, av, b, bv, hit))
            except Exception:  # noqa: BLE001 - one unreadable row never stops the review; it is counted and said below
                failed += 1
    if failed:
        _fault(f"{failed} row(s) of the paper could not be read for a check")
    return out


def _fault(why: str) -> None:
    """A formula stage that did not run in full is a step that did not run: on the run and on the sheet ("Steps that did not run")."""
    from . import faults

    faults.record("aim_formula_checks", "the formula checks", why)


def _carried(conn, book_ids) -> dict[str, tuple[str, dict[int, str]]]:
    from app import agent_review_standards

    from . import library as L

    ids = frozenset(str(b) for b in book_ids)
    if not ids:
        return {}
    entries = {e["id"]: e for e in L.library(conn, within=ids)}
    return {
        b: (
            L.identifier_of(entries[b]),
            dict(agent_review_standards.read_book(conn, b).pages),
        )
        for b in sorted(ids)
        if b in entries
    }


def _line(check, decided, a: Field, av: Val, b: Field, bv: Val, hit: Hit) -> dict:
    from app import blank_markers

    from .steps import CONTRACTOR_FILLED

    label, cmp = decided
    notes = [
        f"formula check {check.id}: code compared both values read from the paper's own rows; the clause's sentence is on page {hit.page} of {hit.standard}"
    ]
    if blank_markers.who_supplies(a.quote) or blank_markers.who_supplies(b.quote):
        notes.append(CONTRACTOR_FILLED)
    compare = {
        "result": "fail" if label == "Not met" else "pass",
        "why": f"{_n(av.high)} {av.unit} {cmp.get('op')} {_n(bv.high * cmp.get('factor', 1.0))} {bv.unit}: "
        + ("false" if label == "Not met" else "true"),
        "paper": [av.high, av.unit],
        "rule": [round(bv.high * cmp.get("factor", 1.0), 9), bv.unit],
        "op": cmp.get("op"),
        "read_from": "verified quotes",
        "converted": cmp.get("converted"),
    }
    compare = {k: v for k, v in compare.items() if v is not None}
    return {
        "item_id": f"F-{check.id}",
        "finding_no": 1,
        "label": label,
        "field": check.title,
        "page": a.page,
        "quote": a.quote,
        "comment": _sentence(check, label, a, av, b, bv, hit, hit.factor),
        "standard": hit.standard,
        "book_document_id": hit.book,
        "clause": check.probe.ref,
        "source": "held standard",
        "topic": check.title,
        "code": "; ".join(notes),
        "numbers": {
            "paper_value": _n(av.high),
            "paper_unit": av.unit,
            "rule_value": _n(bv.high),
            "rule_unit": bv.unit,
        },
        "code_compare": compare,
        "deferred": False,
        "ask": "",
        "read_keys": [a.key, b.key],  # the label keys of the two rows read: `join_into` upgrades only a comment about one of them
    }


#: Two figures are the same figure when their unit code's values (gauge against absolute kept apart) are within this share.
JOIN_WITHIN = 0.005
JOINED = "joined the comment already made on this field and page: its reading is now proven by code"


def _quantities(nums) -> list[tuple] | None:
    """[(unit, reference, value)] of a line's paper value and rule value through the app's unit code; None when either is unreadable."""
    from app import claims

    if not isinstance(nums, dict):
        return None
    out = []
    for value, unit in (
        (nums.get("paper_value"), nums.get("paper_unit")),
        (nums.get("rule_value"), nums.get("rule_unit")),
    ):
        if value in (None, "") or not unit:
            return None
        m = claims.normalise(str(value), str(unit))
        if m.normalized_value is None:
            return None
        out.append((m.normalized_unit, m.reference, m.normalized_value))
    return out


def _same_figure(a: tuple, b: tuple) -> bool:
    return (
        a[0] == b[0]
        and a[1] == b[1]
        and abs(a[2] - b[2]) <= JOIN_WITHIN * max(abs(a[2]), abs(b[2]), 1e-12)
    )


def _same_pair(a: list[tuple], b: list[tuple]) -> bool:
    """The same two figures, whichever of them each line calls the paper's and the rule's."""
    return (_same_figure(a[0], b[0]) and _same_figure(a[1], b[1])) or (
        _same_figure(a[0], b[1]) and _same_figure(a[1], b[0])
    )


_COMBINED = {
    "design_operating_pressure": ("design_pressure", "operating_pressure"),
    "design_operating_temperature": ("design_temperature", "operating_temperature"),
}


def _about(target: dict, keys) -> bool:
    """The comment is about one of the rows the formula read: its field or its verified quote carries that row's label."""
    text = f"{target.get('field') or ''}  {target.get('quote') or ''}"
    wanted = {k for key in keys or [] for k in (key, *_COMBINED.get(key, ()))}
    return any(_LABEL_RX[k].search(text) for k in wanted if k in _LABEL_RX)


def _existing(decided: list[dict], line: dict) -> dict | None:
    """The first line already decided on the SAME page, about the SAME field (its field or quote carries the label of one of the two
    rows the formula read), that makes the SAME comparison (the same two figures through the unit code) and is only an AI opinion or a
    Question (never a line code or the judge already settled, never a value left open). None: no such line."""
    want = _quantities(line.get("numbers"))
    if want is None:
        return None
    for d in decided:
        if (
            d.get("page") != line.get("page")
            or d.get("label") not in ("AI opinion", "Question")
            or d.get("deferred")
            or not _about(d, line.get("read_keys"))
        ):
            continue
        have = _quantities(d.get("numbers"))
        if have is not None and _same_pair(have, want):
            return d
    return None


#: The note that keeps the words an upgrade replaced (completeness: no text is cut without a mark and the full text beside it).
REPLACED = "the AI comment this line replaced read"
_REPLACED = re.compile(re.escape(REPLACED) + r': ("(?:[^"\\]|\\.)*")')


def replaced_of(code_note) -> list[dict]:
    """Each AI comment an upgrade replaced, read back from the line's note: [{"kind": "replaced", "before": the full text}]. Team file only."""
    out = []
    for m in _REPLACED.finditer(str(code_note or "")):
        try:
            out.append({"kind": "replaced", "before": json.loads(m.group(1))})
        except ValueError:
            continue
    return out


def join_into(decided: list[dict], new: list[dict]) -> list[dict]:
    """The formula lines to APPEND to `decided`. A firm Not met whose finding is already a comment on this paper (the same page, the same field,
    the same two figures) does not become a second or third comment: it UPGRADES that line in place (AI opinion -> Not met, proven by code,
    the clause and both quotes of the formula check; the AI comment's own words are kept in the line's note, for the team file) and is not
    appended. A Met line, or a Not met nobody has commented on, is appended as before. Pure."""
    appended = []
    for line in new:
        target = _existing(decided, line) if line.get("label") == "Not met" else None
        if target is None:
            appended.append(line)
            continue
        key = "code" if "code" in target else "code_note"
        before = str(target.get("comment") or "").strip()
        target.update(
            label="Not met", comment=line["comment"], standard=line["standard"], clause=line["clause"], source=line["source"],
            book_document_id=line.get("book_document_id"), numbers=line["numbers"], code_compare=line["code_compare"], deferred=False, ask="",
        )  # fmt: skip
        notes = [line.get("code") or line.get("code_note") or "", JOINED]
        if before:
            notes.append(f"{REPLACED}: {json.dumps(before, ensure_ascii=False)}")
        target[key] = "; ".join(notes).strip("; ")
    return appended


def add_lines(conn, paper, state) -> None:
    """Add the formula lines to the run (`state.decided`), from the rule books the run carried (`join_into`: a finding already commented on is upgraded, not repeated).
    A fault anywhere in this stage is a step that did not run: recorded on the run and shown on the sheet, and the review goes on."""
    try:
        new = lines(conn, paper, sorted(state.books - state.reference_ids))
        state.decided += join_into(state.decided, new)
    except Exception as exc:  # noqa: BLE001 - never stops a finished review
        _fault(exc)
