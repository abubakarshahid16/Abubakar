"""#1690 judge REMOVE rules, differential check on INVENTED rows (no real row text anywhere in the repo).

For every invented row, MATCHED variants (an absence row and a document quote that really states the missing item) and many
MISMATCHED variants (wrong page, other subject, superset, subset, reordered or plural label, No/Not prefixes, a condition the
label does not carry, a different attribute, non-answers such as 0 / 00.0 / 1/A / 'Rev 0', a numeric Fail row removed by a
valued quote, every 'complies' attempt, 'not_applicable', the row's text repeated, absence words ...) go through
`JudgeToolBox` with every figures pair pre-decided 'meets', so the RULES ALONE (second opinion off) must refuse them:
mismatched accepted must be 0. Matched accepted is reported.
"""

import re

from app import agent_judge_rules as rules
from app.agent_judge_tools import JudgeToolBox
from app.agent_tools import InMemoryFindings, ToolContext

ABSENCE_ROWS = [
    ("Gasket material is not specified", "p. 2"),
    ("Paint colour is not stated", "p. 2"),
    ("Welding procedure reference is not given", "p. 4"),
    ("Nozzle schedule is blank", "p. 5"),
    ("Design pressure is not specified", "p. 2"),
    ("Design temperature is missing", "p. 3"),
    ("Set pressure is not stated", "p. 3"),
    ("Corrosion allowance is not given", "p. 4"),
    ("Wall thickness is missing", "p. 4"),
    ("Test pressure is not provided", "p. 6"),
    ("Flow rate is not specified", "pages 6 and 7"),
    ("Name plate data is missing", "p. 3"),
    ("Pressure is not stated", "p. 3"),
    ("Insulation type shall be stated", "p. 2"),
    ("Nozzle size is not stated", ""),
    ("Relief valve tag is not stated", "4.2"),
]
NUMERIC_ROWS = [
    ("Design pressure of 14 bar exceeds the limit of 12 bar", "p. 2"),
    ("Design temperature of 90 degC is above the limit of 80 degC", "p. 3"),
    ("Wall thickness of 8 mm is below the required 10 mm", "p. 4"),
    ("Set pressure of 12 bar is not enough", "p. 5"),
    ("Corrosion allowance of 3 mm is missing", "p. 4"),
]
NON_ANSWERS = ["0", "000", "00.0", "00.0 bar", "N/A 1", "1/A", "TBD 2024", "Rev 0", "ID 123", "0 (none)", "1 N/A", "0 items", "1/1/1900", "-", "+0", "0.0 bar", "9999", "1", "1 not stated", "2 - see note", "#1", "(1)", "one", "3.2 of the specification", "2 of 5", "12 items", "5 foo", "2024-13-45", "pending", "void", "empty", "nil", "none", "unavailable", "under review", "to follow", "by others", "see note", "in progress", "later", "99 psi", "12 mm"]  # fmt: skip
ABSENCE = ["not provided", "omitted", "no information", "does not state", "lacks", "to be advised", "TBA", "N/A", "as per vendor standard", "missing", "blank", "not yet issued", "no data", "not applicable", "awaiting", "deferred", "withheld", "not declared", "tbd", "zzz qqq", "draft"]  # fmt: skip


def label_of(comment):
    words, out = re.split(r"[0-9:=(;\[]", comment)[0].split(), []
    for w in words:
        if w.lower() in {"is", "are", "of", "shall", "to", "the", "a"}:
            break
        out.append(w)
    return " ".join(out)


def make_box(row, pages, clause_text):
    ctx = ToolContext(
        allowed_document_ids=frozenset({"D1", "S1"}),
        document_id="D1",
        editions={"ISO 9999": "2021"},
    )
    ctx.findings = InMemoryFindings()
    box = JudgeToolBox(
        ctx,
        {"R": row},
        page_reader=lambda d, p: pages.get(p) if d == "D1" else None,
        searcher=lambda q, a: {},
        standard_pages=lambda d: [(1, clause_text)],
        edition_evidence=lambda s, e: {
            "status": "confirmed",
            "doc": "S1",
            "page": 1,
            "quote": "x",
            "source": "t",
        },
    )
    ctx.current_item = "R"
    return box


def attempt(row, pages, clause_text, **args):
    """True when the RULES accept this REMOVE (every compared pair is pre-decided 'meets')."""
    box = make_box(row, pages, clause_text)
    dq, cq = args.get("doc_quote"), args.get("clause_quote")
    if dq and cq:
        box._compares[(dq.strip(), cq.strip())] = {"decided": True, "verdict": "meets"}
        args.setdefault("figures", [{"doc_quote": dq, "clause_quote": cq}])
    out = box.run(
        "judge_row",
        {"decision": "REMOVE", "standard": "ISO 9999", "clause": "4.2", **args},
    )["result"]
    return (
        bool(out.get("accepted")) and box.ctx.findings.get("R")["decision"] == "REMOVE"
    )


def valued(label):
    """A value of the right kind for the label (what a document that really states the item would print)."""
    low = label.lower()
    if "pressure" in low:
        return "12 bar"
    if "temperature" in low:
        return "80 degC"
    if "thickness" in low or "allowance" in low:
        return "5 mm"
    if "flow" in low:
        return "40 m3/h"
    return "2024-05-01"


class Tally:
    def __init__(self):
        self.matched_total = self.matched_accepted = self.mismatched_total = (
            self.mismatched_accepted
        ) = 0
        self.leaks = []

    def rec(self, kind, accepted, matched, comment):
        if matched:
            self.matched_total += 1
            self.matched_accepted += accepted
        else:
            self.mismatched_total += 1
            if accepted:
                self.mismatched_accepted += 1
                self.leaks.append((kind, comment[:40]))


def run_row(comment, cell, t):
    row = {
        "comment": comment,
        "page_section": cell,
        "standard_reference": "ISO 9999 4.2",
    }
    pg = rules.row_pages(row)
    page = pg[0] if pg else 2
    other = 9 if page != 9 else 8
    label = label_of(comment)
    value = valued(label)
    docq = f"{label}: {value}"
    clq = f"{label} shall be documented."
    clause = f"4.2 Marking\n{clq}\nOther requirement Z shall be 3 mm.\n4.3 Scope\nThis clause does not apply to {label} units.\n"
    base = f"Paint colour: grey\nDesign general notes shall apply\n{label}: pending\n"

    def go(kind, matched=False, code="already_stated", **kw):
        kw.setdefault("page", page)
        kw.setdefault("doc_quote", docq)
        kw.setdefault("clause_quote", clq)
        pp = kw.pop("pages", None)
        if pp is None:
            pp = {page: base + kw["doc_quote"], other: kw["doc_quote"]}
        r = kw.pop("row", row)
        t.rec(kind, attempt(r, pp, clause, reason_code=code, **kw), matched, comment)

    go("matched", True)
    go("matched complies-as-note", False, code="complies")
    if pg:
        go("wrong page", page=other)
        go(
            "page in comment",
            page=other,
            row={**row, "comment": f"{comment} (p.{other})"},
        )
    go("other subject", doc_quote="Paint colour: 10 bar")
    go(
        "generic only",
        doc_quote="Design general notes shall apply",
        clause_quote="Design general notes shall apply as general.",
    )
    go(
        "not_applicable",
        code="not_applicable",
        clause="4.3",
        clause_quote=f"This clause does not apply to {label} units.",
    )
    for v in NON_ANSWERS:
        # harness note: "99 psi" really states a pressure and "12 mm" a thickness or allowance, so for those labels the
        # variant is a MATCHED statement (not a mismatch); everywhere else it is a wrong-quantity value and must be refused
        really_states = (v == "99 psi" and "pressure" in label.lower()) or (v == "12 mm" and ("thickness" in label.lower() or "allowance" in label.lower()))  # fmt: skip
        go("non-answer", matched=really_states, doc_quote=f"{label}: {v}")
    for v in ABSENCE:
        go("absence value", doc_quote=f"{label}: {v}")
    words = label.split()
    for kind, quote in (
        ("superset", f"{label} drop: {value}"), ("superset2", f"{label} approval status: {value}"), ("subset", f"{words[0]}: {value}"),
        ("reordered", f"{' '.join(reversed(words))}: {value}"), ("plural", f"{label}s: {value}"), ("not prefix", f"Not {label}: {value}"),
        ("no prefix", f"No {label}: {value}"), ("without prefix", f"Without {label}: {value}"), ("vendor prefix", f"Vendor {label}: {value}"),
        ("number in label", f"{label} 2: {value}"), ("ref value", f"{label}: 3.2 of the specification"), ("table cell", f"{label} | 10 | bar"),
        ("see page", f"{label}: see page 4"), ("own text", comment[:60]), ("own text as value", f"{label}: " + " ".join(comment.split()[:10])),
    ):  # fmt: skip
        if len(words) > 1 or kind not in {"subset", "reordered"}:
            go(kind, doc_quote=quote)
    go(
        "condition",
        row={**row, "comment": f"{label} for the second case is not stated"},
    )
    go("condition2", row={**row, "comment": f"{label} when operating is missing"})
    go(
        "different attribute",
        row={**row, "comment": f"{label} unit of measure is not stated"},
        doc_quote=f"{label}: 4471 bar",
    )
    return bool(rules.row_subject(comment))


def run_numeric(comment, cell, t):
    """A numeric FAIL row (the claim is a figure against a limit): nothing may remove it, by any path."""
    row = {
        "comment": comment,
        "page_section": cell,
        "standard_reference": "ISO 9999 4.2",
    }
    page = (rules.row_pages(row) or [2])[0]
    label = label_of(comment)
    n, u = rules.figures_in(comment)[0]
    clause = f"4.2 Marking\n{label} shall not exceed 12 {u}.\n{label} shall be at least 8 {u}.\n{label} shall not exceed 20 {u}.\n"
    cases = [
        (
            "AS own figure",
            "already_stated",
            f"{label}: {n} {u}",
            f"{label} shall not exceed 12 {u}.",
        ),
        (
            "AS limit figure",
            "already_stated",
            f"{label}: 12 {u}",
            f"{label} shall not exceed 12 {u}.",
        ),
        (
            "AS zero",
            "already_stated",
            f"{label}: 0",
            f"{label} shall not exceed 12 {u}.",
        ),
        (
            "AS 00.0",
            "already_stated",
            f"{label}: 00.0 {u}",
            f"{label} shall not exceed 12 {u}.",
        ),
        (
            "AS psi",
            "already_stated",
            f"{label}: 99 psi",
            f"{label} shall not exceed 12 {u}.",
        ),
        (
            "C own figure",
            "complies",
            f"{label}: {n} {u}",
            f"{label} shall not exceed 12 {u}.",
        ),
        (
            "C limit as document figure",
            "complies",
            f"{label}: 12 {u}",
            f"{label} shall not exceed 12 {u}.",
        ),
        (
            "C loose clause sentence",
            "complies",
            f"{label}: {n} {u}",
            f"{label} shall not exceed 20 {u}.",
        ),
        (
            "C min sentence for an exceeds claim",
            "complies",
            f"{label}: {n} {u}",
            f"{label} shall be at least 8 {u}.",
        ),
        (
            "C superset",
            "complies",
            f"{label} drop: {n} {u}",
            f"{label} shall not exceed 12 {u}.",
        ),
        (
            "C condition",
            "complies",
            f"{label}: {n} {u} at 50 degC",
            f"{label} shall not exceed 12 {u}.",
        ),
        ("C psi", "complies", f"{label}: 10 psi", f"{label} shall not exceed 12 {u}."),
    ]
    for kind, code, dq, cq in cases:
        pages = {page: dq, page + 6: dq}
        t.rec(
            kind,
            attempt(
                row,
                pages,
                clause,
                reason_code=code,
                page=page,
                doc_quote=dq,
                clause_quote=cq,
            ),
            False,
            comment,
        )


def run_all():
    t, usable = Tally(), 0
    for comment, cell in ABSENCE_ROWS:
        usable += run_row(comment, cell, t)
    for comment, cell in NUMERIC_ROWS:
        run_numeric(comment, cell, t)
    return t, usable


def test_mismatched_variants_accepted_by_the_rules_alone_is_zero():
    t, usable = run_all()
    print(f"rows {len(ABSENCE_ROWS) + len(NUMERIC_ROWS)}, usable subject {usable}, matched accepted {t.matched_accepted}/{t.matched_total}, "
          f"mismatched accepted {t.mismatched_accepted}/{t.mismatched_total}")  # fmt: skip
    assert t.mismatched_total > 1000
    assert t.leaks == [], t.leaks[:5]
    assert t.mismatched_accepted == 0


def test_matched_variants_are_still_accepted_where_the_rules_can_verify_them():
    t, usable = run_all()
    assert usable >= 10 and t.matched_accepted >= 8  # narrowed, not dead
    assert (
        t.matched_accepted < t.matched_total
    )  # rows with no usable subject, page cell or absence claim cannot be removed


def test_a_matched_absence_row_is_accepted_so_the_check_is_not_vacuous():
    t = Tally()
    run_row("Design pressure is not specified", "p. 2", t)
    assert t.matched_accepted >= 1 and t.mismatched_accepted == 0
