"""#1475 planted-defect sets for PROCEDURES: invented procedures, invented requirements, a fake model.

Why: a reviewer that never says Fail is not a reviewer (77 runs, 0 NON_COMPLIANT). The datasheet set is
`test_1475_planted_defects.py`. This is the procedure half, on the PF1 pattern (#881): invented documents carry
planted defects next to controls, and the test asserts what the CURRENT code can honestly do, not what we wish.

What the current code can honestly do with a procedure (CLAUDE.md rule 4, top rule AI-first):
  * the procedure path (`procedure_text`, #1476/#1489) looks the requirement up in the document's own page
    text. Found = an engineer row with page + a quote proved to be real page text. Not found = an engineer row
    that the run counts in ONE "no passage found" note naming the requirement. NEVER COMPLIANT, NEVER Fail:
    code cannot judge a contradiction, so a contradicting step surfaces as the quote, for the engineer;
  * the AI clause review (`clause_review`, #1477/#1493) is a fake here: scripted answers, one of them a
    fabricated quote that code must drop.

Planted defect types: (a) a required section missing, (b) a step that contradicts the requirement, (c) a number
that breaks a requirement, (d) a control: satisfied, must not read missing or compliant. Every planted defect
must surface to the engineer. The two numeric gaps this set found are closed by #1476 (numeric limits take the procedure path).

Every document and requirement below is INVENTED (rule 13): no real standard or procedure text.
"""

from __future__ import annotations

import pytest

from app import clause_review, comparison, db, procedure_text, standards
from app import requirements_3b as r3b
from app.config import settings

# the fixtures and the fake provider of the clause review tests: reused, not copied (autouse fixtures included)
from tests.test_1477_clause_review import (  # noqa: F401
    Fake,
    _go,
    _procedure,
    _resolver,
    _rows,
)
from tests.test_b3_page_ledger import _review, temp_storage  # noqa: F401 - autouse

A, B, C, D = "a_missing", "b_contradicts", "c_number", "d_control"

# ---------------------------------------------------------------------------- the invented procedures
HAZOP_PAGES = [
    "Purpose. This procedure sets out how a HAZOP study is carried out on a process unit. "
    "Roles. The HAZOP facilitator may be a member of the design team when no other facilitator is free. "
    "A scribe records every deviation.",
    "Study method. The unit is split into nodes. Each node is defined on the P&ID with its design intent, "
    "and the guide words no, more, less and reverse are applied to every node.",
    "Revalidation. The HAZOP study is revalidated every 10 years or after a major modification. "
    "Recommendations are listed in the study report.",
]
SIL_PAGES = [
    "SIL determination. The target SIL of each safety instrumented function is set by a layer of protection "
    "analysis. The LOPA team records the initiating event frequency and every independent protection layer.",
    "Verification. The achieved SIL is calculated from the failure rates of the sensor, logic solver and final "
    "element. Proof tests are carried out every 36 months. The SIL team leader may be the project manager.",
]
HOTWORK_PAGES = [
    "Hot work permit. A hot work permit is issued by the welding supervisor before any welding or cutting "
    "starts. Each permit is valid for a single shift of 12 hours.",
    "Precautions. A fire watch stays at the work site during the work and for 30 minutes after it ends. "
    "Gas testing is done before the work starts.",
]

#: Planted steps the keyword path cannot find because the document says it in other words ("independent of the
#: work crew" against "issued by the welding supervisor"): they surface in the counted "no passage found" note,
#: and only the AI clause review reads them. Honest, not a pass: still an engineer row.
PATH_NOTE = frozenset({"W2"})

# (clause, requirement, planted type, page the document says it on or None, the sentence to quote)
HAZOP = [
    (
        "H1",
        "The study team shall include a process engineer, an operations representative and a maintenance representative.",
        A,
        None,
        None,
    ),
    (
        "H2",
        "Recommendations shall be tracked to closure with a named owner and a due date in an action register.",
        A,
        None,
        None,
    ),
    (
        "H3",
        "The HAZOP facilitator shall be independent of the design team.",
        B,
        1,
        "The HAZOP facilitator may be a member of the design team when no other facilitator is free.",
    ),
    (
        "H4",
        "The HAZOP study shall be revalidated at least every 5 years.",
        C,
        3,
        "The HAZOP study is revalidated every 10 years or after a major modification.",
    ),
    (
        "H5",
        "Each node shall be defined on the P&ID with its design intent.",
        D,
        2,
        "Each node is defined on the P&ID with its design intent, and the guide words no, more, less and reverse are applied to every node.",
    ),
]
SIL = [
    (
        "S1",
        "The systematic capability of each device shall be demonstrated for the target SIL.",
        A,
        None,
        None,
    ),
    (
        "S2",
        "The SIL team leader shall be independent of the project manager.",
        B,
        2,
        "The SIL team leader may be the project manager.",
    ),
    (
        "S4",
        "Proof tests shall be carried out at least every 12 months.",
        C,
        2,
        "Proof tests are carried out every 36 months.",
    ),
    (
        "S3",
        "The target SIL of each safety instrumented function shall be determined by layer of protection analysis.",
        D,
        1,
        "The target SIL of each safety instrumented function is set by a layer of protection analysis.",
    ),
]
HOTWORK = [
    (
        "W1",
        "A fire extinguisher of suitable type shall be kept at the work location.",
        A,
        None,
        None,
    ),
    (
        "W2",
        "The permit shall be issued by an authority independent of the work crew.",
        B,
        1,
        "A hot work permit is issued by the welding supervisor before any welding or cutting starts.",
    ),
    (
        "W3",
        "A fire watch shall remain at the work site during hot work.",
        D,
        2,
        "A fire watch stays at the work site during the work and for 30 minutes after it ends.",
    ),
]
# Numbers phrased as a numeric limit ("at most", "at least ... months/hours"): the extractor classifies these
# as numeric_limit, not as a statement - see the gap tests.
NUMERIC = [
    (
        "W4",
        "Each hot work permit shall be valid for a maximum of 8 hours.",
        C,
        1,
        "Each permit is valid for a single shift of 12 hours.",
    ),
    (
        "W5",
        "Each hot work permit shall be valid for a maximum of 12 hours.",
        D,
        1,
        "Each permit is valid for a single shift of 12 hours.",
    ),
]
DOCS = {
    "hazop": (HAZOP_PAGES, HAZOP),
    "sil": (SIL_PAGES, SIL),
    "hotwork": (HOTWORK_PAGES, HOTWORK),
}


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "clause_review_enabled", True)


def _pages(texts):
    return list(enumerate(texts, start=1))


def _req(text, clause):
    """A requirement dict the way the extractor classifies the sentence (no hand-set type)."""
    limit = r3b.parse_limit(text)
    return {
        "id": clause,
        "clause": clause,
        "requirement_type": r3b.classify(text, limit),
        "operator": (limit or {}).get("operator"),
        "raw_value": (limit or {}).get("raw_value"),
        "raw_unit": (limit or {}).get("raw_unit"),
        "field": r3b.field_name(text),
        "requirement_text": text,
        "source_text": text,
        "required_evidence_type": r3b.required_evidence_type(text),
    }


def _check(rows, texts):
    """Every row through the procedure path: {clause: verdict}."""
    pages = _pages(texts)
    with procedure_text.using(pages):
        return {
            clause: comparison.compare(_req(text, clause), None)
            for clause, text, *_ in rows
        }


def _all_rows():
    return [(*row, texts) for texts, rows in DOCS.values() for row in rows]


# ---------------------------------------------------------------------------- layer 1: the procedure path


def test_the_planted_text_is_really_in_the_documents():
    """Non-vacuity of the set: a defect is only planted if its sentence is on the stated page."""
    numeric = [(HOTWORK_PAGES, NUMERIC)]
    for texts, rows in [*DOCS.values(), *numeric]:
        for clause, _text, kind, page, quote in rows:
            if kind == A:
                continue
            assert page is not None and quote in " ".join(texts[page - 1].split()), (
                clause
            )
    # and the missing ones really are absent: no required words of them appear together in any sentence
    for texts, rows in DOCS.values():
        for clause, text, kind, *_ in rows:
            if kind == A:
                assert procedure_text.find_passage(text, _pages(texts)) is None, clause


@pytest.mark.parametrize("name", sorted(DOCS))
def test_no_row_of_a_procedure_is_compliant_failed_or_sent_to_another_document(name):
    texts, rows = DOCS[name]
    for clause, verdict in _check(rows, texts).items():
        assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW, clause
        assert verdict["status"] not in (
            comparison.COMPLIANT,
            comparison.NON_COMPLIANT,
            comparison.NOT_IN_DOCUMENT_SCOPE,
            comparison.MISSING_INFORMATION,
        ), clause


@pytest.mark.parametrize("name", sorted(DOCS))
def test_a_present_step_surfaces_as_its_verified_page_and_quote(name):
    """(b) contradicting, (c) number as a statement, (d) control: an engineer row with the real sentence."""
    texts, rows = DOCS[name]
    verdicts = _check(rows, texts)
    pages = dict(_pages(texts))
    seen = 0
    for clause, _text, kind, page, quote in rows:
        if kind == A or clause in PATH_NOTE:
            continue
        seen += 1
        why = verdicts[clause]["rationale"]
        assert why.startswith(procedure_text.FOUND), clause
        assert f"found on page {page}:" in why, clause
        assert procedure_text.page_of(None, why) == page
        shown = why.split('"')[1]
        assert shown in " ".join(pages[page].split()), (
            clause
        )  # the quote is real page text
        assert quote.startswith(shown) or shown in quote, clause
        assert (
            "engineer to confirm" in why
            and "not a finding that the requirement is met" in why
        )
    assert seen


@pytest.mark.parametrize("name", sorted(DOCS))
def test_a_contradiction_is_the_quote_for_the_engineer_not_a_fail(name):
    """(b) code cannot judge contradiction: honest expectation is NEEDS_ENGINEER_REVIEW + the quote."""
    texts, rows = DOCS[name]
    verdicts = _check(rows, texts)
    for clause, _t, kind, page, _q in rows:
        if kind == B:
            assert verdicts[clause]["status"] == "NEEDS_ENGINEER_REVIEW"
            assert verdicts[clause]["status"] != comparison.NON_COMPLIANT
            if clause in PATH_NOTE:
                assert procedure_text.is_unfound(
                    {"reason_code": verdicts[clause]["rationale"]}
                )
            else:
                assert f"found on page {page}:" in verdicts[clause]["rationale"]


def test_every_missing_section_is_counted_and_named_in_the_one_no_passage_note():
    """(a) a missing section: not a quote, not MISSING_INFORMATION; ONE counted note naming each requirement."""
    findings, missing = [], []
    for texts, rows in DOCS.values():
        for clause, verdict in _check(rows, texts).items():
            findings.append(
                {
                    "clause": clause,
                    "reason_code": verdict["rationale"].split(":")[0],
                    "ai_rationale": verdict["rationale"],
                }
            )
        missing += [c for c, _t, kind, *_ in rows if kind == A or c in PATH_NOTE]
    [note] = procedure_text.notes(findings, lambda f: f["clause"])
    assert note["count"] == len(missing) == 5
    for clause in missing:
        assert clause in note["detail"]
    for clause in (
        "H3",
        "H4",
        "H5",
        "S2",
        "S3",
        "S4",
        "W3",
    ):  # a found row is never in that note
        assert clause not in note["detail"]
    assert "5 requirements of this run have no passage found" in note["detail"]


def test_a_satisfied_control_is_never_read_as_missing_or_compliant():
    """(d) the control rows: found, so neither in the 'no passage' note nor COMPLIANT."""
    for name, (texts, rows) in DOCS.items():
        verdicts = _check(rows, texts)
        for clause, _t, kind, *_ in rows:
            if kind == D:
                assert procedure_text.is_found(
                    {"reason_code": verdicts[clause]["rationale"]}
                ), (name, clause)
                assert not procedure_text.is_unfound(
                    {"reason_code": verdicts[clause]["rationale"]}
                )


def test_the_switch_off_state_is_the_old_wrong_path_so_the_set_is_not_vacuous():
    """Without the procedure path a statement goes to 'another document' (the 274-row defect):
    the expectations above only hold because the path reads the document."""
    for clause, text, *_ in HAZOP:
        verdict = comparison.compare(
            _req(text, clause), None
        )  # no pages: not a procedure review
        assert verdict["status"] == comparison.NOT_IN_DOCUMENT_SCOPE


@pytest.mark.parametrize("clause", ["W4", "W5"])
def test_numeric_requirements_classify_as_numeric_limit_today(clause):
    """Pins the premise of the gap, so a changed classifier cannot silently make the numeric tests below meaningless."""
    text = next(t for c, t, *_ in NUMERIC if c == clause)
    assert _req(text, clause)["requirement_type"] == "numeric_limit"


@pytest.mark.parametrize("clause", ["W4"])
def test_a_numeric_limit_the_procedure_breaks_surfaces_to_the_engineer_with_its_quote(
    clause,
):
    """(c) the planted number: expected an engineer row with the page and the real sentence."""
    _c, text, _k, page, _q = next(row for row in NUMERIC if row[0] == clause)
    with procedure_text.using(_pages(HOTWORK_PAGES)):
        verdict = comparison.compare(_req(text, clause), None)
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert f"found on page {page}:" in verdict["rationale"]
    # the code states the two numbers in words and does not judge them
    assert (
        "the procedure states 12 hours; the requirement is at most 8 hours"
        in (verdict["rationale"])
    )
    assert "engineer to confirm" in verdict["rationale"]


def test_a_satisfied_numeric_control_is_not_read_as_missing():
    """(d) numeric control (12 hours against a 12 hour limit): must not read MISSING_INFORMATION."""
    _c, text, *_ = next(row for row in NUMERIC if row[0] == "W5")
    with procedure_text.using(_pages(HOTWORK_PAGES)):
        verdict = comparison.compare(_req(text, "W5"), None)
    assert verdict["status"] != comparison.MISSING_INFORMATION


def test_a_numeric_limit_is_never_compliant_or_failed_by_the_procedure_path_today():
    """The honest floor while the gap stands: whatever it says, it does not pass or fail the number."""
    for clause, text, *_ in NUMERIC:
        with procedure_text.using(_pages(HOTWORK_PAGES)):
            verdict = comparison.compare(_req(text, clause), None)
        assert verdict["status"] not in (
            comparison.COMPLIANT,
            comparison.NON_COMPLIANT,
            comparison.NOT_IN_DOCUMENT_SCOPE,
        ), clause


# ---------------------------------------------------------------------------- layer 2: the AI clause review (fake model)

FABRICATED = "The HAZOP study is revalidated every 5 years by an external auditor appointed by the regulator."


def _world(name, extra=()):
    texts, rows = DOCS[name]
    rows = [*rows, *extra]
    sub = _procedure(doc_id=f"doc_{name}", kind="procedure", pages=tuple(texts))
    run, scope = _review(sub)
    with db.connect() as conn:
        conn.execute("DELETE FROM standard_requirements")
    for clause, text, *_ in rows:
        standards.create_requirement(
            standard_document_id="doc_std",
            chunk_id="sc",
            clause=clause,
            page=1,
            requirement_text=text,
            source_text=text,
        )
    return run, scope, rows


def _script(rows, *, fabricate=()):
    """What a good reader would answer: nothing for a missing section, the real sentence otherwise;
    for `fabricate` clauses a quote that is not in the document."""
    answers = {}
    for clause, text, kind, page, quote in rows:
        if clause in fabricate:
            answers[text] = {"answer": "quote", "page": page, "quote": FABRICATED}
        elif kind == A:
            answers[text] = {"answer": "no_evidence", "page": None, "quote": None}
        else:
            answers[text] = {"answer": "quote", "page": page, "quote": quote}
    return answers


@pytest.mark.parametrize("name", sorted(DOCS))
def test_clause_review_every_requirement_gets_one_engineer_row_never_compliant(
    name, on
):
    run, scope, rows = _world(name)
    status = _go(run, scope, Fake(_script(rows)))
    got = {r["standard_clause"]: r for r in _rows(run)}
    assert set(got) == {c for c, *_ in rows}
    assert status["requirements"] == len(rows) and status["not_reviewed_count"] == 0
    for r in got.values():
        assert r["compliance_status"] == "NEEDS_ENGINEER_REVIEW"
        assert r["compliance_status"] not in ("COMPLIANT", "NON_COMPLIANT")
        assert r["confirmed_by"] is None and r["origin"] == clause_review.ORIGIN
    assert status["verified"] == sum(1 for *_x, k, _p, _q in rows if k != A)
    assert status["no_evidence"] == sum(1 for *_x, k, _p, _q in rows if k == A)


@pytest.mark.parametrize("name", sorted(DOCS))
def test_clause_review_a_present_step_row_carries_the_verified_page_and_quote(name, on):
    run, scope, rows = _world(name)
    _go(run, scope, Fake(_script(rows)))
    got = {r["standard_clause"]: r for r in _rows(run)}
    for clause, _t, kind, page, quote in rows:
        if kind == A:
            continue
        assert got[clause]["contractor_page"] == page, clause
        assert got[clause]["contractor_evidence_text"] == quote, clause
        assert got[clause]["finding"].startswith(clause_review.TEXT_VERIFIED)


@pytest.mark.parametrize("name", sorted(DOCS))
def test_clause_review_a_missing_section_says_engineer_to_check_not_missing_or_compliant(
    name, on
):
    run, scope, rows = _world(name)
    _go(run, scope, Fake(_script(rows)))
    got = {r["standard_clause"]: r for r in _rows(run)}
    for clause, _t, kind, *_ in rows:
        if kind != A:
            continue
        r = got[clause]
        assert "found none" in r["finding"] and "engineer to check" in r["finding"]
        assert r["contractor_page"] is None and r["contractor_evidence_text"] is None
        assert "compl" not in r["finding"].lower().replace("complies", "")
        assert r["compliance_status"] == "NEEDS_ENGINEER_REVIEW"


def test_clause_review_a_fabricated_quote_is_dropped_for_the_planted_number(on):
    """(c) the model invents a quote for the revalidation step: code drops it, the row says so."""
    run, scope, rows = _world("hazop")
    status = _go(run, scope, Fake(_script(rows, fabricate={"H4"})))
    got = {r["standard_clause"]: r for r in _rows(run)}
    h4 = got["H4"]
    assert status["unverified"] == 1
    assert (
        "could not be verified" in h4["finding"]
        and "engineer to check" in h4["finding"]
    )
    assert h4["contractor_evidence_text"] is None and h4["contractor_page"] is None
    assert "external auditor" not in h4["finding"]
    # the other rows are untouched by the drop
    assert (
        got["H3"]["contractor_evidence_text"] and got["H5"]["contractor_evidence_text"]
    )


def test_clause_review_reaches_the_numeric_requirements_the_procedure_path_cannot(on):
    """The AI lane covers (c) written as a numeric limit: the 12 hour permit and the 36 month proof test
    each surface as an engineer row with the page and the real sentence. (Partial answer to the gap.)"""
    run, scope, rows = _world("hotwork", extra=NUMERIC)
    _go(run, scope, Fake(_script(rows)))
    got = {r["standard_clause"]: r for r in _rows(run)}
    for clause in ("W4", "W5"):
        assert got[clause]["compliance_status"] == "NEEDS_ENGINEER_REVIEW"
        assert got[clause]["contractor_page"] == 1
        assert "12 hours" in got[clause]["contractor_evidence_text"]
    assert not any(r["compliance_status"] == "COMPLIANT" for r in got.values())


def test_clause_review_findings_are_not_counted_in_a_headline(on):
    """Suggestions never enter a count: planted defects do not inflate or deflate any tally."""
    run, scope, rows = _world("sil")
    _go(run, scope, Fake(_script(rows)))
    findings = _rows(run)
    assert findings and clause_review.without_rows(findings) == []
