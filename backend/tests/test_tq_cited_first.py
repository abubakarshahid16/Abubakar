"""A technical query's evidence: what the FORM itself cites is looked up first (the owner's faults of 26 Nov 2026, fault 4;
`technical_query_cited`). Invented contracts and forms; no model, no network (the general search is a stand-in)."""

from __future__ import annotations

import pytest

from app import technical_query_cited as TC
from app import technical_query_contracts as TQC
from tests.test_aim_method_helpers import _doc, open_aim_db

SCHED_C, SCHED_D = "doc_zq_sched_c", "doc_zq_sched_d"
CLAUSE_PAGE = (
    "4.1 Invented general\nThe invented general clause text stands here.\n"
    "4.2 Invented coating thickness\nThe invented coating shall be at least 250 microns thick.\n"
    "4.3 Invented next clause\nAnother invented clause."
)


@pytest.fixture
def library(tmp_path, monkeypatch):
    gen = open_aim_db(tmp_path, monkeypatch)
    conn = next(gen)
    with conn:
        _doc(
            conn,
            SCHED_C,
            "ZQ-SCHEDULE-C.pdf",
            "CONTRACT_DOCUMENT",
            {
                1: "SCHEDULE C\nINVENTED TECHNICAL REQUIREMENTS\n1 Scope",
                2: "Invented page two, see clause 4.2 below.",
                3: CLAUSE_PAGE,
            },
        )
        _doc(conn, SCHED_D, "ZQ-SCHEDULE-D.pdf", "CONTRACT_DOCUMENT", {1: "SCHEDULE D\nINVENTED PRICES\n1 Rates"})  # fmt: skip
    yield conn
    next(gen, None)


def test_the_form_names_its_schedule_and_clause_on_one_line_and_nothing_else_is_tied_to_it():
    """Measured on the stored queries (26 Nov 2026): a form's clause numbers on other lines, or beside a standard's name, were
    clauses of company standards or of another Schedule. So a clause belongs to a Schedule only on the Schedule's own line, with no
    standard named there (the first rule, "a clause alone joins the one Schedule", was wrong on real forms and is gone)."""
    assert TC.cited(
        [
            "Subject: invented coating\nReference: Schedule C, Clause 4.2\nPlease confirm."
        ]
    ) == [((("schedule", "C"), None), "4.2")]
    assert TC.cited(
        ["Ref. Schedule C\nThe vendor asks about section 4.2 and article 7"]
    ) == [((("schedule", "C"), None), None)]
    assert TC.cited(["Schedule C, see API 610 clause 6.1"]) == [
        ((("schedule", "C"), None), None)
    ]  # a standard's clause, not the Schedule's
    two = TC.cited(["Schedule C and Schedule D apply", "clause 4.2"])
    assert two == [((("schedule", "C"), None), None), ((("schedule", "D"), None), None)]
    assert TC.cited(["An invented question with no reference at all, 25 microns"]) == []


def test_the_cited_clause_of_the_cited_schedule_is_found_on_its_page_and_listed_first(
    library,
):
    hits, said = TC.lookup(
        ["Reference: Schedule C, Clause 4.2"], [SCHED_C, SCHED_D], lambda doc: []
    )
    assert [
        (h["document_id"], h["page_start"], h["locator"], h["cited"]) for h in hits
    ] == [(SCHED_C, 3, "Schedule C, clause 4.2", True)]
    assert (
        hits[0]["text"].startswith("4.2 Invented coating thickness")
        and "250 microns" in hits[0]["text"]
    )
    assert (
        hits[0]["text"] in CLAUSE_PAGE
    )  # verbatim: checked on its page like any passage
    assert said == ["Schedule C clause 4.2: found on page 3"]


def test_a_mention_of_the_clause_is_not_its_heading(library):
    """Page 2 mentions "clause 4.2"; only page 3 has a line that BEGINS with it."""
    page, _text = TC.clause_passage(
        {2: "Invented page two, see clause 4.2 below.", 3: CLAUSE_PAGE}, "4.2"
    )
    assert page == 3
    assert (
        TC.clause_passage({3: CLAUSE_PAGE}, "4.20") is None
        and TC.clause_passage({3: CLAUSE_PAGE}, "4") is None
    )


def test_a_schedule_not_held_held_twice_or_a_clause_not_found_is_said_and_nothing_is_listed(
    library,
):
    hits, said = TC.lookup(
        ["Schedule F, clause 1.1"], [SCHED_C, SCHED_D], lambda doc: []
    )
    assert hits == [] and said == [
        "Schedule F clause 1.1: not held among the contracts you may read"
    ]
    hits, said = TC.lookup(["Schedule C, clause 9.9"], [SCHED_C], lambda doc: [])
    assert hits == [] and said == [
        "Schedule C clause 9.9: the clause was not found in that contract"
    ]
    with library:
        _doc(
            library,
            "doc_zq_sched_c2",
            "ZQ-SCHEDULE-C-copy.pdf",
            "CONTRACT_DOCUMENT",
            {1: "SCHEDULE C\nINVENTED COPY"},
        )
    hits, said = TC.lookup(
        ["Schedule C, clause 4.2"], [SCHED_C, "doc_zq_sched_c2"], lambda doc: []
    )
    assert hits == [] and said == [
        "Schedule C clause 4.2: held more than once, not chosen"
    ]


def test_a_contract_the_caller_may_not_read_is_never_looked_at(library):
    hits, said = TC.lookup(
        ["Schedule C, clause 4.2"], [SCHED_D], lambda doc: []
    )  # Schedule C is not among the readable ones
    assert hits == [] and "not held among the contracts you may read" in said[0]


def test_a_schedule_named_with_no_clause_is_searched_first(library):
    asked = []

    def one(doc):
        asked.append(doc)
        return [
            {
                "document_id": doc,
                "page_start": 1,
                "page_end": 1,
                "text": "Invented passage of the cited schedule.",
            }
        ]

    hits, said = TC.lookup(
        ["Please see Schedule D for the invented rates"], [SCHED_C, SCHED_D], one
    )
    assert (
        asked == [SCHED_D]
        and hits[0]["cited"]
        and said == ["Schedule D: searched first (1 passage)"]
    )


def test_search_all_lists_the_cited_passage_first_then_the_general_search_without_repeating_it(
    library, monkeypatch
):
    general = {SCHED_C: [{"document_id": SCHED_C, "page_start": 2, "page_end": 2, "text": "Invented general hit.", "rerank_score": -8.3}],
               SCHED_D: [{"document_id": SCHED_D, "page_start": 1, "page_end": 1, "text": "Invented rates hit.", "rerank_score": -9.0}]}  # fmt: skip
    monkeypatch.setattr(TQC, "_one", lambda question, doc: list(general.get(doc, [])))
    allowed = frozenset({SCHED_C, SCHED_D})
    out = TQC.search_all(
        "invented noisy question words",
        allowed,
        cited_from=["Ref: Schedule C, clause 4.2"],
    )
    assert out["hits"][0]["cited"] and out["hits"][0]["page_start"] == 3
    assert [h.get("text") for h in out["hits"][1:]] == [
        "Invented general hit.",
        "Invented rates hit.",
    ]
    assert (
        "Looked up first, as the form cites them: Schedule C clause 4.2: found on page 3."
        in out["coverage"]["line"]
    )
    plain = TQC.search_all(
        "invented noisy question words", allowed
    )  # no form: as before
    assert (
        not any(h.get("cited") for h in plain["hits"])
        and "Looked up first" not in plain["coverage"]["line"]
    )
    assert plain["coverage"]["cited_first"] == []


def test_of_two_contracts_that_are_the_same_schedule_the_higher_recorded_revision_is_chosen(
    library,
):
    """As a contract review chooses its reference papers (`references.pick`): never a guess, the highest RECORDED revision."""
    with library:
        _doc(
            library,
            "doc_zq_sched_c_rev",
            "ZQ-SCHEDULE-C-rev2.pdf",
            "CONTRACT_DOCUMENT",
            {1: "SCHEDULE C\nINVENTED REVISION", 3: CLAUSE_PAGE},
        )
        library.execute(
            "UPDATE document_classification SET revision = '1' WHERE document_id = ?",
            (SCHED_C,),
        )
        library.execute(
            "UPDATE document_classification SET revision = '2' WHERE document_id = 'doc_zq_sched_c_rev'"
        )
    assert TC.which([SCHED_C, "doc_zq_sched_c_rev"], (("schedule", "C"), None)) == [
        "doc_zq_sched_c_rev"
    ]
    hits, said = TC.lookup(
        ["Schedule C, clause 4.2"], [SCHED_C, "doc_zq_sched_c_rev"], lambda doc: []
    )
    assert hits[0]["document_id"] == "doc_zq_sched_c_rev" and said == [
        "Schedule C clause 4.2: found on page 3"
    ]


def test_an_attachment_named_after_its_schedule_on_the_line_is_that_schedules_attachment_and_its_section_is_found(
    library,
):
    """The real forms' shape: "Schedule B - Attachment V, Rev 6, Section 7.2" (the part reader joins a higher part only when it
    comes after); here invented as Attachment II of Schedule C."""
    with library:
        _doc(library, "doc_zq_c_att2", "ZQ-C-ATT-II.pdf", "CONTRACT_DOCUMENT",
             {1: "SCHEDULE C\nATTACHMENT II\nINVENTED STUDY", 2: "3.1 Invented study basis\nThe invented basis is 12 bar."})  # fmt: skip
    line = "REF.1 INVENTED SCOPE SCHEDULE C \u2013 ATTACHMENT II, Rev06, Section 3.1"
    assert TC.cited([line]) == [((("attachment", "II"), ("schedule", "C")), "3.1")]
    hits, said = TC.lookup([line], [SCHED_C, SCHED_D, "doc_zq_c_att2"], lambda doc: [])
    assert [(h["document_id"], h["page_start"]) for h in hits] == [("doc_zq_c_att2", 2)]
    assert said == ["Attachment II of Schedule C clause 3.1: found on page 2"]
