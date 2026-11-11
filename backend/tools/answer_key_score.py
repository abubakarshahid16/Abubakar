"""Score a CRS workbook against an answer key by FIELD ROLE and PAPER PAGE (owner answer 5, 11 Nov 2026).

WHY. The earlier answer-key scorer (kept on the owner's machine, not in git) called a key row "found" when
the key comment's words and a page digit appeared anywhere in one CRS row - the reasoning and quote columns
included. On the 11 Nov runs that counted 19 of 23 found where a hand check found 12, and 8 "clear wrong"
where the hand check found 0. A word in a reasoning cell is not the same problem.

THE RULE. A CRS line answers a key row only when BOTH hold:
  field - one of the key row's field roles is a role the line's field label names; and
  page  - one of the key row's paper pages is one of the line's pages. A key row with no page (the field is
          absent from every page of the paper) is held to the field alone.
A WRONG (or disputed) key row is one comment the key rejects: a field and page raised against one clause.
A line repeats it only when it answers the row AND cites the same clause (the key's own "Standard
Reference"); a line on that field and page under another clause is a different comment the key has not
judged, and is counted apart ("other clause, not judged"), never as clear wrong.
The old word match is still computed, but only as a REPORTED fallback ("word only"): it is never counted
as found, as clear wrong, or as anything else.

THE KEY. The answer key stays outside the repo (it is built from a client CRS). It is an .xlsx whose header
row holds these columns; any other columns are kept for people and ignored here:
  Field role      the roles of the field the row is about, ";"-separated. A role is a key of `roles` in
                  `app/reference/datasheet_checks.json` (the field registry), or a procedure element
                  "<playbook id>:<element id>" of `app/reference/playbooks/`. Empty: the row is about no
                  field (it can never be matched, and is counted as such).
  Paper page      the paper's own page numbers ("3", "1-4", "1-2, 4"); empty when the field is absent.
  Scored as       problem | complies | wrong | disputed | not scored.
  Printed label   optional: how this paper prints the field when the registry does not name it, ";"-separated.
The row number is the sheet's own row number, as people quote it ("key row 56").

THE CRS. The product's CRS layout: a header row starting "Item No" with "Page No./Section" and
"COMPANY Comments". Lines on the sheet "CRS" are comment lines; a CRS line carrying the tick marker or the
verdict Pass, and every line on a sheet whose name starts with "Passed" (or whose title is the tick-sheet
title), is a pass line. Other sheets (internal notes, not applicable, unproven AI passes) are not read.

THE NUMBERS (each with its denominator, rows by sheet row number):
  problems found          problem rows a comment line answers            of the problem rows
  complies confirmed      complies rows a pass line answers              of the complies rows
  clear wrong             wrong rows a comment line repeats              of the wrong rows
  disputed raised         disputed rows a comment line repeats           reported apart, never scored
  other clause            wrong or disputed rows only answered under another clause (not judged)
  wrong passes            problem rows no comment line answers but a pass line does
  word only (fallback)    rows the old word match would have counted that field and page do not

No document text is printed: counts, row numbers, roles and pages only. Pure: no database, no network.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

import openpyxl

PLAYBOOKS = Path(__file__).resolve().parents[1] / "app" / "reference" / "playbooks"

SCORED_AS = ("problem", "complies", "wrong", "disputed", "not scored")
KEY_FIELD, KEY_PAGE, KEY_KIND, KEY_LABEL = (
    "Field role",
    "Paper page",
    "Scored as",
    "Printed label",
)
CRS_SHEET = "CRS"
TICK_TITLE = "passed by a tested rule: engineer to tick"
TICK_MARKERS = ("ENGINEER TO TICK", "TICKED BY ENGINEER")
PASS_VERDICTS = ("pass",)

_PAGE_PART = re.compile(r"^\s*(p\.\s*[0-9]|page not found|pages? [0-9])", re.I)
_NOT_READ = re.compile(r"^\s*not read from the (data ?sheet|paper)", re.I)
_LEAD_PAGE = re.compile(
    r"^\s*(.{1,120}?)\s*(?:\(pages? ([0-9][0-9,\s\-\u2013]*)\)\s*:|(?<=\s)on pages? ([0-9][0-9,\s\-\u2013]*))"
)
_CLAUSE = re.compile(r"\s([A-Z]{0,4}-?\d+(?:\.\d+)*[a-z]?)\s*$")
_READ_ON = re.compile(r"\bon pages? ([0-9][0-9,\s\-\u2013]*(?:and [0-9]+)?)", re.I)


class AnswerKeyError(ValueError):
    """The answer key cannot be scored as written. The message names the sheet row."""


@dataclass(frozen=True)
class KeyRow:
    row: int
    scored_as: str
    roles: frozenset
    pages: frozenset
    spellings: tuple = ()
    words: tuple = ()  # the old word match's words (fallback only)
    clause: tuple | None = (
        None  # (standard, clause) of the key row's own Standard Reference
    )


@dataclass(frozen=True)
class Line:
    sheet: str
    row: int
    label: str
    pages: frozenset
    text: str
    is_pass: bool
    roles: frozenset = field(default=frozenset())
    clause: tuple | None = None


def fold(text) -> str:
    return " ".join(str(text or "").lower().replace(":", " ").split())


def _words(text) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(text))


def parse_pages(text) -> frozenset:
    """'3', '1-4', '1-2, 4', '1, 2 and 4' -> the page numbers; anything else adds nothing."""
    pages: set[int] = set()
    for lo, hi in re.findall(r"(\d+)\s*(?:[-\u2013]\s*(\d+))?", str(text or "")):
        a, b = int(lo), int(hi or lo)
        if 1 <= a <= b <= a + 500:
            pages.update(range(a, b + 1))
    return frozenset(pages)


def clause_ref(text) -> tuple | None:
    """'API 520-I 5.5', 'API-520-I clause 5.5', 'SAES-J-600 6.1 (p.9)', 'X-1 (edition not recorded) cl. 5'
    -> (standard, clause) with the standard folded to letters and digits and a trailing year dropped.
    'API 610 datasheet annex' -> ('API610', None): a standard named with no clause number. None: no standard."""
    t = re.sub(r"\((?:p\.|pages?|edition)[^)]*\)", " ", str(text or ""), flags=re.I)
    t = " " + re.sub(r"\.pdf\b|\bclause\b|\bcl\.", " ", t, flags=re.I).strip()
    m = _CLAUSE.search(t)
    head, clause = (t[: m.start()], m.group(1).upper().lstrip("-")) if m else (t, None)
    std_tokens = []
    for token in head.split():
        if not re.search(r"[A-Z0-9]", token):
            break  # the standard's id ends at the first plain word ('datasheet annex')
        std_tokens.append(token)
    std = re.sub(
        r"(19|20)\d\d$", "", re.sub(r"[^A-Z0-9]", "", "".join(std_tokens).upper())
    )
    return (std, clause) if std else None


def _cut_qualifier(label: str) -> str:
    """'Set pressure (TAG-1 A/B (for X))' -> 'Set pressure': a bracket after the name qualifies it."""
    return label.split(" (", 1)[0].strip(" :-")


def line_label(page_section, comment) -> str:
    """The field label of one CRS line, from the product's own CRS layout:
    "p.<pages> - <label> (<qualifier>)", "page not found ... - Not read from the datasheet (N pages) - <label>",
    "<label>: A value was read on pages ...", or a comment that starts "<label> (page N): ...". '' if none."""
    page_section = str(page_section or "").strip()
    parts = [p.strip() for p in page_section.split(" - ") if p.strip()]
    rest = [p for p in parts if not _PAGE_PART.match(p) and not _NOT_READ.match(p)]
    if parts and rest and rest[0] is parts[0] and ":" in parts[0]:
        return _cut_qualifier(parts[0].split(":", 1)[0])
    if rest and len(parts) > 1:
        return _cut_qualifier(rest[0])
    lead = _LEAD_PAGE.match(str(comment or ""))
    return _cut_qualifier(lead.group(1)) if lead else ""


def line_pages(page_section, comment) -> frozenset:
    """The paper pages of one CRS line: "p.<pages>" first, then "... on pages N, M", then a comment lead
    "<label> (page N):". No page: empty."""
    page_section = str(page_section or "")
    m = re.match(r"\s*p\.\s*([0-9][0-9,\s\-\u2013]*)", page_section)
    if m:
        return parse_pages(m.group(1))
    m = _READ_ON.search(page_section)
    if m:
        return parse_pages(m.group(1))
    lead = _LEAD_PAGE.match(str(comment or ""))
    return parse_pages(lead.group(2) or lead.group(3)) if lead else frozenset()


@lru_cache(maxsize=1)
def _playbook_elements() -> frozenset:
    out = set()
    for path in sorted(PLAYBOOKS.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.update(f"{data['id']}:{e['id']}" for e in data.get("elements", []))
    return frozenset(out)


def _registry():
    from app import datasheet_checks

    rules = datasheet_checks.load_rules()
    return rules, {
        role: datasheet_checks.label_patterns(role, rules) for role in rules["roles"]
    }


def known_role(role: str, rules: dict) -> bool:
    return role in rules["roles"] or role in _playbook_elements()


def _spelling_names(spelling: str, label_words: list[str]) -> bool:
    """Every word of the key's printed label is a word of the line's label (a shared 4-letter stem counts)."""
    want = _words(spelling)
    if not want or not label_words:
        return False
    return all(
        any(w == lw or (len(w) >= 4 and lw[:4] == w[:4]) for lw in label_words)
        for w in want
    )


def _span(pattern: re.Pattern, folded: str) -> tuple | None:
    """Where a registry pattern names the label: it must span the whole label, or at least two of its words.
    One shared word inside a longer label ("type" in "conn. type") is not that field. None: not named."""
    m = pattern.search(folded)
    if not m:
        return None
    span = m.group(0).strip(" .,;:/")
    if span == folded.strip(" .,;:/") or len(span.split()) >= 2:
        return m.start(), m.end()
    return None


def roles_named(label: str, patterns: dict, spellings: dict | None = None) -> frozenset:
    """The registry roles a field label names (the registry's own label patterns, unanchored, and its
    synonyms), plus the roles whose key spelling this label prints. A role named only inside a longer name
    another role holds ("relieving temper" inside "viscosity at relieving temper") is dropped."""
    folded = fold(label)
    if not folded:
        return frozenset()
    spans = {}
    for role, pats in patterns.items():
        got = [sp for sp in (_span(p, folded) for p in pats) if sp]
        if got:
            spans[role] = max(got, key=lambda sp: sp[1] - sp[0])
    found = {
        r
        for r, (a, b) in spans.items()
        if not any(
            a2 <= a and b <= b2 and (b2 - a2) > (b - a)
            for r2, (a2, b2) in spans.items()
            if r2 != r
        )
    }
    words = _words(label)
    for role, spelled in (spellings or {}).items():
        if any(_spelling_names(s, words) for s in spelled):
            found.add(role)
    return frozenset(found)


# ------------------------------------------------------------------ the key


def _header_index(rows: list) -> int:
    for i, row in enumerate(rows):
        cells = [str(c or "").strip() for c in row]
        if KEY_FIELD in cells and KEY_PAGE in cells and KEY_KIND in cells:
            return i
    raise AnswerKeyError(
        f"no header row with the columns {KEY_FIELD!r}, {KEY_PAGE!r} and {KEY_KIND!r}"
    )


def read_key(path, rules: dict | None = None, sheet: str | None = None) -> list[KeyRow]:
    """The key's rows. Raises AnswerKeyError naming the sheet row on a value it cannot score honestly:
    an unknown 'Scored as', a role the registry does not hold, a page that is not a page number."""
    rules = rules if rules is not None else _registry()[0]
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = (
        wb[sheet]
        if sheet
        else next((w for w in wb.worksheets if _has_key_header(w)), wb.worksheets[0])
    )
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    hi = _header_index(rows)
    head = [str(c or "").strip() for c in rows[hi]]
    col = {name: head.index(name) for name in (KEY_FIELD, KEY_PAGE, KEY_KIND)}
    label_col = head.index(KEY_LABEL) if KEY_LABEL in head else None
    page_section = (
        head.index("Page No./Section") if "Page No./Section" in head else None
    )
    std_col = head.index("Standard Reference") if "Standard Reference" in head else None
    out = []
    for number, row in enumerate(rows[hi + 1 :], start=hi + 2):
        cells = row + [None] * (len(head) - len(row))
        kind = fold(cells[col[KEY_KIND]])
        if not kind:
            if any(c not in (None, "") for c in cells):
                raise AnswerKeyError(f"row {number}: {KEY_KIND!r} is empty")
            continue
        if kind not in SCORED_AS:
            raise AnswerKeyError(
                f"row {number}: {KEY_KIND!r} must be one of {', '.join(SCORED_AS)}"
            )
        roles = frozenset(
            r.strip() for r in str(cells[col[KEY_FIELD]] or "").split(";") if r.strip()
        )
        unknown = sorted(r for r in roles if not known_role(r, rules))
        if unknown:
            raise AnswerKeyError(
                f"row {number}: not a role of the field registry: {', '.join(unknown)}"
            )
        page_text = str(cells[col[KEY_PAGE]] or "").strip()
        if page_text and not re.fullmatch(
            r"[0-9,\s\-\u2013]+|[0-9,\s]+and\s+[0-9]+", page_text
        ):
            raise AnswerKeyError(
                f"row {number}: {KEY_PAGE!r} must be page numbers ('3', '1-4', '1-2, 4')"
            )
        spellings = (
            tuple(
                s.strip() for s in str(cells[label_col] or "").split(";") if s.strip()
            )
            if label_col is not None
            else ()
        )
        printed = (
            line_label(cells[page_section], "") if page_section is not None else ""
        )
        words = tuple(
            w for w in _words(spellings[0] if spellings else printed) if len(w) > 2
        )
        clause = clause_ref(cells[std_col]) if std_col is not None else None
        out.append(
            KeyRow(
                number, kind, roles, parse_pages(page_text), spellings, words, clause
            )
        )
    return out


def _has_key_header(ws) -> bool:
    for row in ws.iter_rows(values_only=True, max_row=30):
        cells = [str(c or "").strip() for c in row]
        if KEY_FIELD in cells and KEY_KIND in cells:
            return True
    return False


def key_spellings(key: list[KeyRow]) -> dict:
    out: dict[str, set] = {}
    for k in key:
        for role in k.roles:
            out.setdefault(role, set()).update(k.spellings)
    return {r: tuple(sorted(s)) for r, s in out.items() if s}


# ------------------------------------------------------------------ the CRS


def _text(row) -> str:
    return " ".join(str(c) for c in row if c not in (None, ""))


def read_crs(path) -> list[Line]:
    """Every comment line and pass line of a CRS workbook in the product's layout."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        first = fold(rows[0][0] if rows and rows[0] else "")
        pass_sheet = ws.title.lower().startswith("passed") or first == TICK_TITLE
        if ws.title != CRS_SHEET and not pass_sheet:
            continue
        hi = next((i for i, r in enumerate(rows) if r and r[0] == "Item No"), None)
        if hi is None:
            continue
        head = [str(c or "").strip() for c in rows[hi]]
        if "Page No./Section" not in head:
            continue
        pi = head.index("Page No./Section")
        ci = head.index("COMPANY Comments") if "COMPANY Comments" in head else None
        vi = head.index("Verdict") if "Verdict" in head else None
        si = head.index("Standard Reference") if "Standard Reference" in head else None
        for number, row in enumerate(rows[hi + 1 :], start=hi + 2):
            if (
                not row
                or row[0] in (None, "")
                or sum(1 for c in row if c not in (None, "")) < 3
            ):
                continue
            row = row + [None] * (len(head) - len(row))
            text = _text(row)
            comment = row[ci] if ci is not None else ""
            verdict = fold(row[vi]) if vi is not None else ""
            is_pass = (
                pass_sheet
                or any(m in text for m in TICK_MARKERS)
                or verdict in PASS_VERDICTS
            )
            out.append(
                Line(
                    ws.title,
                    number,
                    line_label(row[pi], comment),
                    line_pages(row[pi], comment),
                    text,
                    is_pass,
                    clause=clause_ref(row[si]) if si is not None else None,
                )
            )
    return out


# ------------------------------------------------------------------ the score


def answers(k: KeyRow, line: Line) -> bool:
    """The rule: a shared field role AND (a shared page, or a key row with no page)."""
    return bool(k.roles & line.roles) and (not k.pages or bool(k.pages & line.pages))


def repeats(k: KeyRow, line: Line) -> bool:
    """A wrong (or disputed) key row is ONE comment: a field and page raised against one clause. A line
    repeats it when it answers the row AND cites the same standard and clause (the same standard alone when
    the key names no clause number); when the key row names no standard, the field and page alone decide.
    A line on the same field and page under another clause is a different comment the key does not judge
    ("other clause, not judged")."""
    if not answers(k, line):
        return False
    if k.clause is None:
        return True
    std, clause = k.clause
    return (
        line.clause is not None
        and line.clause[0] == std
        and (clause is None or line.clause[1] == clause)
    )


def _word_match(k: KeyRow, line: Line) -> bool:
    """The old scorer's test, kept as a reported fallback only: the key's words (4-letter stems) and one of
    its pages appear anywhere in the line's cells."""
    if not k.words:
        return False
    t = line.text.lower()
    return all(w[:4] in t for w in k.words) and (
        not k.pages or any(str(p) in t for p in k.pages)
    )


def score(key: list[KeyRow], lines: list[Line], patterns: dict) -> dict:
    spellings = key_spellings(key)
    lines = [
        replace(ln, roles=roles_named(ln.label, patterns, spellings)) for ln in lines
    ]
    comments = [ln for ln in lines if not ln.is_pass]
    passes = [ln for ln in lines if ln.is_pass]
    of = {kind: [k.row for k in key if k.scored_as == kind] for kind in SCORED_AS}
    res = {
        "problems_found": [],
        "complies_confirmed": [],
        "clear_wrong": [],
        "disputed_raised": [],
        "wrong_passes": [],
        "complies_raised_as_comment": [],
        "word_only": {
            kind: [] for kind in ("problem", "complies", "wrong", "disputed")
        },
        "other_clause_not_judged": {"wrong": [], "disputed": []},
        "key_rows_without_field": {
            kind: [k.row for k in key if k.scored_as == kind and not k.roles]
            for kind in SCORED_AS
            if kind != "not scored"
        },
        "of": {kind: len(rows) for kind, rows in of.items()},
        "comment_lines": len(comments),
        "pass_lines": len(passes),
        "lines_without_field_role": sum(1 for ln in lines if not ln.roles),
        "lines_without_page": sum(1 for ln in lines if not ln.pages),
        "matched_lines": {},
    }
    for k in key:
        if k.scored_as == "not scored":
            continue
        test = repeats if k.scored_as in ("wrong", "disputed") else answers
        hit = [ln for ln in comments if test(k, ln)]
        hit_pass = [ln for ln in passes if test(k, ln)]
        on_crs = bool(hit)
        if test is repeats and not on_crs and any(answers(k, ln) for ln in comments):
            res["other_clause_not_judged"][k.scored_as].append(k.row)
        if k.scored_as == "problem":
            if on_crs:
                res["problems_found"].append(k.row)
            elif hit_pass:
                res["wrong_passes"].append(k.row)
        elif k.scored_as == "complies":
            if hit_pass:
                res["complies_confirmed"].append(k.row)
            if on_crs:
                res["complies_raised_as_comment"].append(k.row)
        elif k.scored_as == "wrong" and on_crs:
            res["clear_wrong"].append(k.row)
        elif k.scored_as == "disputed" and on_crs:
            res["disputed_raised"].append(k.row)
        pool = passes if k.scored_as == "complies" else comments
        counted = bool(hit_pass) if k.scored_as == "complies" else on_crs
        if not counted and any(_word_match(k, ln) for ln in pool):
            res["word_only"][k.scored_as].append(k.row)
        if hit or hit_pass:
            res["matched_lines"][k.row] = sorted(
                {f"{ln.sheet}!{ln.row}" for ln in hit + hit_pass}
            )
    return res


def score_files(key_path, crs_path, sheet: str | None = None) -> dict:
    rules, patterns = _registry()
    return score(read_key(key_path, rules, sheet), read_crs(crs_path), patterns)


def summary(res: dict) -> dict:
    """The counts only, each with its denominator."""
    of = res["of"]
    return {
        "problems_found": f"{len(res['problems_found'])} of {of['problem']}",
        "complies_confirmed": f"{len(res['complies_confirmed'])} of {of['complies']}",
        "clear_wrong": f"{len(res['clear_wrong'])} of {of['wrong']}",
        "disputed_raised": f"{len(res['disputed_raised'])} of {of['disputed']}",
        "wrong_passes": len(res["wrong_passes"]),
        "other_clause_not_judged": {
            k: len(v) for k, v in res["other_clause_not_judged"].items()
        },
        "word_only_not_counted": {k: len(v) for k, v in res["word_only"].items()},
        "comment_lines": res["comment_lines"],
        "pass_lines": res["pass_lines"],
        "lines_without_field_role": res["lines_without_field_role"],
    }
