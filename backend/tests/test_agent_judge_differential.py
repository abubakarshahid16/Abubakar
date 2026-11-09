"""#1690 judge REMOVE rules, differential check on INVENTED rows (no real row text anywhere in the repo).

For every invented row, matched variants (the quotes really are about the row) and many mismatched variants (wrong page,
other subject, superset or subset subject, absence and valueless quotes, not_applicable, the row's text repeated, a page
cited in the comment, a wrong figure, the 14-versus-12 mix-up ...) go through `JudgeToolBox` with every figures pair
pre-decided 'meets', so the RULES ALONE must refuse: mismatched accepted must be 0. Matched accepted is reported.
"""

import re

import pytest

from app import agent_judge_rules as rules
from app.agent_judge_tools import JudgeToolBox
from app.agent_tools import InMemoryFindings, ToolContext

ROWS = [
    ("Operating temperature of 85 C exceeds the permitted 80 C", "p. 2"),
    ("Relief valve set pressure of 12 bar is below the required 15 bar", "p. 3"),
    ("Flow rate of 40 m3/h is above the limit of 35 m3/h", "p. 2"),
    ("Shell thickness of 8 mm is under the required 10 mm", "p. 4"),
    ("Corrosion allowance of 3 mm is not enough", "p. 5"),
    ("Hydrotest pressure of 30 bar is wrong", "pages 6 and 7"),
    ("Gasket material is not specified", "p. 2"),
    ("Name plate data is missing", "p. 3"),
    ("Welding procedure reference is not given", "p. 4"),
    ("Paint colour is not specified", "p. 2"),
    ("Data is missing", "p. 2"),
    ("Design data are missing", "p. 3"),
    ("Pressure is wrong", "p. 3"),
    ("Insulation type shall be stated", ""),
    ("Nozzle schedule is incomplete", "4.2"),
]
ABSENCE = [
    "not provided", "omitted", "no information", "does not state", "lacks", "to be advised", "TBA", "N/A", "-", "see note",
    "as per vendor standard", "missing", "unavailable", "none", "nil", "pending", "TBC", "blank", "void", "empty", "to follow",
    "by others", "not yet available", "under review", "in progress", "later", "not indicated", "not listed", "without value",
    "never issued", "no data", "not applicable", "awaiting", "deferred", "withheld", "not declared", "tbd", "zzz qqq", "draft",
]  # fmt: skip


def label_of(comment):
    head = re.split(r"[0-9:=(;\[]", comment)[0]
    words = head.split()
    out = []
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
    figs = args.pop("figures", None)
    if figs:
        for f in figs:
            box._compares[(f["doc_quote"].strip(), f["clause_quote"].strip())] = {
                "decided": True,
                "verdict": "meets",
            }
        args["figures"] = figs
    out = box.run(
        "judge_row",
        {"decision": "REMOVE", "standard": "ISO 9999", "clause": "4.2", **args},
    )["result"]
    return (
        bool(out.get("accepted")) and box.ctx.findings.get("R")["decision"] == "REMOVE"
    )


def run_row(comment, cell, stats):
    row = {
        "comment": comment,
        "page_section": cell,
        "standard_reference": "ISO 9999 4.2",
    }
    subject = rules.row_subject(comment)
    pg = rules.row_pages(row)
    page = pg[0] if pg else 2
    other = 9 if page != 9 else 8
    label = label_of(comment)
    numeric = rules.numeric_row(comment)
    figs = rules.figures_in(comment)
    n, u = figs[0] if figs else ("10", "bar")
    value = f"{n} {u}" if numeric else "12 items"
    clause_value = max(int(float(n.replace(",", "."))) - 2, 1) if numeric else 0
    docq = f"{label}: {value}"
    clq = (
        f"{label} shall be at least {clause_value} {u}"
        if numeric
        else f"{label} shall be documented."
    )
    clause = f"4.2 Marking\n{clq}.\nOther requirement Z shall be 3 mm.\n4.3 Scope\nThis clause does not apply to {label} units.\n4.5 General\n{label} shall be general.\n"
    base = f"{docq}\n{label} units: {value}\nPaint colour: grey\nDesign general notes shall apply\n{label}: pending"
    pages = {page: base, other: docq}

    def rec(kind, accepted, matched):
        key = "matched" if matched else "mismatched"
        stats[key + "_total"] += 1
        if accepted:
            stats[key + "_accepted"] += 1
            if not matched:
                stats["leaks"].append((kind, comment[:40]))

    fig = [{"doc_quote": docq, "clause_quote": clq + "."}] if numeric else None
    rec(
        "matched complies",
        attempt(
            row,
            pages,
            clause,
            reason_code="complies",
            page=page,
            doc_quote=docq,
            clause_quote=clq + ".",
            **({"figures": fig} if fig else {}),
        ),
        True,
    )
    rec(
        "matched already_stated",
        attempt(
            row,
            pages,
            clause,
            reason_code="already_stated",
            page=page,
            doc_quote=docq,
            clause_quote=clq + ".",
        ),
        True,
    )

    def mis(kind, code, **kw):
        kw.setdefault("page", page)
        kw.setdefault("doc_quote", docq)
        kw.setdefault("clause_quote", clq + ".")
        pp = kw.pop("pages", pages)
        if numeric and code == "complies" and "figures" not in kw:
            kw["figures"] = [
                {"doc_quote": kw["doc_quote"], "clause_quote": kw["clause_quote"]}
            ]
        rec(kind, attempt(row, pp, clause, reason_code=code, **kw), False)

    if pg:
        mis("wrong page", "complies", page=other)
        mis("wrong page AS", "already_stated", page=other)
    mis("other subject doc", "complies", doc_quote="Paint colour: grey")
    mis("other subject doc AS", "already_stated", doc_quote="Paint colour: grey")
    mis(
        "other subject clause",
        "complies",
        clause_quote="Other requirement Z shall be 3 mm.",
    )
    mis(
        "generic only",
        "complies",
        doc_quote="Design general notes shall apply",
        clause="4.5",
        clause_quote=f"{label} shall be general.",
    )
    mis(
        "not_applicable",
        "not_applicable",
        doc_quote=f"{label} units: {value}",
        clause="4.3",
        clause_quote=f"This clause does not apply to {label} units.",
    )
    for word in ABSENCE:
        qd = f"{label}: {word}"
        for code in ("complies", "already_stated"):
            mis(
                "absence " + code,
                code,
                doc_quote=qd,
                pages={**pages, page: base + "\n" + qd},
            )
    for variant, kind in (
        (f"{label} approval status", "superset"),
        (label.split()[0], "subset"),
    ):
        qd = f"{variant}: {value}"
        for code in ("complies", "already_stated"):
            mis(
                kind + " " + code,
                code,
                doc_quote=qd,
                pages={**pages, page: base + "\n" + qd},
            )
    qd = comment[:60]
    mis(
        "repeats row text",
        "already_stated",
        doc_quote=qd,
        pages={**pages, page: base + "\n" + qd},
    )
    if numeric:
        wrong = f"{label}: {int(float(n.replace(',', '.'))) + 50} {u}"
        mis(
            "wrong figure",
            "complies",
            doc_quote=wrong,
            clause_quote=f"{label} shall be at least {n} {u}",
            pages={**pages, page: base + "\n" + wrong},
        )
    mis("page in comment", "already_stated", page=other, pages={**pages, other: docq})
    return subject


def run_all():
    stats = {
        "matched_total": 0,
        "matched_accepted": 0,
        "mismatched_total": 0,
        "mismatched_accepted": 0,
        "leaks": [],
    }
    derivable = sum(1 for c, cell in ROWS if run_row(c, cell, stats))
    return stats, derivable


def test_mismatched_variants_accepted_by_the_rules_alone_is_zero():
    stats, derivable = run_all()
    print(f"rows {len(ROWS)}, usable subject {derivable}, matched accepted {stats['matched_accepted']}/{stats['matched_total']}, "
          f"mismatched accepted {stats['mismatched_accepted']}/{stats['mismatched_total']}")  # fmt: skip
    assert stats["mismatched_total"] > 1000
    assert stats["leaks"] == [], stats["leaks"][:5]
    assert stats["mismatched_accepted"] == 0


def test_matched_variants_are_still_accepted_where_the_rules_can_verify_them():
    stats, derivable = run_all()
    assert (
        derivable >= 8 and stats["matched_accepted"] >= derivable
    )  # narrowed, not dead
    assert (
        stats["matched_accepted"] < stats["matched_total"]
    )  # rows with no usable subject or page cannot be removed


@pytest.mark.parametrize(
    "comment", ["Operating temperature of 85 C exceeds the permitted 80 C"]
)
def test_a_matched_numeric_row_is_accepted_so_the_check_is_not_vacuous(comment):
    stats = {
        "matched_total": 0,
        "matched_accepted": 0,
        "mismatched_total": 0,
        "mismatched_accepted": 0,
        "leaks": [],
    }
    run_row(comment, "p. 2", stats)
    assert stats["matched_accepted"] == 2 and stats["mismatched_accepted"] == 0
