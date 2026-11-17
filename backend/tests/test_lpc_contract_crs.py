"""LPC (order 14, 17 Nov 2026): the contract CRS made honest with general rules only. Invented papers, numbers and words.

P1  a contract under general review is given the papers of its SAME package (same labelled cover number, role contract) that it
    names by their label, as project papers on the plan's leaving list; only papers the caller may read; never another package.
P2  a reference to a held schedule resolves to that paper; only a labelled part we do not hold is "not held", named by its label.
C2  a cited name that is a heading of the paper (or that the paper places in its own article) is its own part, never a missing book.
C3  a blank to fill found by code on a page is one Query row "blank to be filled before signing" with that page.
C4  a quote shown as evidence on a general review's CRS is a full sentence, else the row says it holds no quote.
C5  sheet 1's document number and revision come from the cover when code finds them there, else "not found on the cover".
"""

from __future__ import annotations

import pytest

from app import (
    agent_general_crs,
    agent_general_review,
    classification,
    contract_checks,
    contract_package,
    crs_ai_header,
    crs_ai_words,
    db,
    quote_sentence,
    review_engine,
    review_leaving,
    review_points,
    review_points_service,
)
from tests.test_b1_review_engine import _doc, open_facts
from tests.test_p3_review_jobs import temp_storage, world  # noqa: F401 - fixtures

NUMBER = "QX-7781-ZZ"  # invented
OTHER_NUMBER = "QX-9999-YY"  # invented: another package
AGREEMENT = [
    (1, f"Invented Works Programme     AGREEMENT No. {NUMBER}\nForm of Agreement\nPage 1 of 3\nRev 04\n"
        "1.\nPARTIES\nThis Agreement is made on ______ day of ________, 2031.\n"
        'SCHEDULE "P"  Price and Payment\nSCHEDULE "Q"\nTaxes and Duties\n'),
    (2, f"Invented Works Programme     AGREEMENT No. {NUMBER}\n2.\nWORK START AND TIME FOR FINISHING\n"
        "The Builder shall start the work on the date stated in Schedule P.\n"
        "The Agreement Papers listed in Sub-Article 1.1 of this Agreement form the whole agreement.\n"
        "3.\nPAYMENT\nThe Owner shall pay the sum of ____________ Dollars (USD ..........) as set out in SCHEDULE P.\n"
        "Contents of the schedules ..................... 12\n"),
    (3, f"Invented Works Programme     AGREEMENT No. {NUMBER}\nSignature: ____________\nName: ____________\n"),
]  # fmt: skip
SCHEDULE_P = [(1, f"Invented Works Programme     AGREEMENT No. {NUMBER}\nSCHEDULE “P” - Price and Payment\nPage 1 of 2\n"
                  "The Owner shall pay the price in the stages set out below for the whole of the work.\n")]  # fmt: skip
ATTACHMENT_P = [(1, f"Invented Works Programme     AGREEMENT No. {NUMBER}\nSCHEDULE “P” - Attachment I - Rate Sheet\n"
                    "The rates below apply to all work ordered under the agreement and its schedules.\n")]  # fmt: skip
FOREIGN_P = [(1, f"Another Invented Programme     AGREEMENT No. {OTHER_NUMBER}\nSCHEDULE “P” - Price\n"
                 "The Owner shall pay the price of this other agreement in four stages as set out below.\n")]  # fmt: skip


def _paper(doc_id: str, pages, role="CONTRACT_DOCUMENT", n: int = 1) -> str:
    _doc(doc_id, f"{n:02d}" * 32, role, filename=f"{doc_id} invented.pdf")
    with db.connect() as conn:
        for page, text in pages:
            conn.execute("INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?,?,?,1,0)",
                         (doc_id, page, text))  # fmt: skip
    return doc_id


@pytest.fixture
def package(temp_storage):  # noqa: F811
    ids = {
        "agreement": _paper("agr_1", AGREEMENT, n=81),
        "sched_p": _paper("sch_p", SCHEDULE_P, n=82),
        "att_p": _paper("att_p", ATTACHMENT_P, n=83),
        "foreign": _paper("for_p", FOREIGN_P, n=84),
    }
    ids["all"] = frozenset(v for v in ids.values())
    return ids


# --------------------------------------------------------------------------------------------- C5 the cover


def test_the_cover_gives_the_labelled_number_and_the_revision_never_a_page_count():
    cover = contract_package.cover_id(AGREEMENT)
    assert (cover.number, cover.number_label, cover.number_page, cover.revision) == (
        NUMBER,
        "AGREEMENT No.",
        1,
        "04",
    )
    nothing = contract_package.cover_id(
        [(1, "An invented note\nPage 1 of 2\nREVISIONS TO THE CODES\n")]
    )
    assert (
        nothing.number is None and nothing.revision is None
    )  # "Page 1 of 2" and "REVISIONS" are not a number or a revision


def test_sheet_one_says_the_cover_number_or_not_found_on_the_cover(package):
    conn = db.connect()
    head = crs_ai_header.with_cover(
        conn, package["agreement"], {"document_number": "", "revision": ""}
    )
    assert (
        head["document_number"] == f"{NUMBER} (AGREEMENT No.)"
        and head["revision"] == "04"
    )
    _paper("bare_1", [(1, "An invented memo with no number on its cover.\n")], n=85)
    bare = crs_ai_header.with_cover(
        conn, "bare_1", {"document_number": "", "revision": ""}
    )
    assert bare["document_number"] == bare["revision"] == crs_ai_header.NOT_ON_COVER
    held = crs_ai_header.with_cover(
        conn, "bare_1", {"document_number": "INV-1", "revision": "B"}
    )
    assert (held["document_number"], held["revision"]) == (
        "INV-1",
        "B",
    )  # no cover value: the value the app holds


# --------------------------------------------------------------------------------------------- P1 the package


def test_the_package_is_the_same_cover_number_and_role_contract_and_the_callers_scope(
    package,
):
    conn = db.connect()
    got = {
        p["document_id"]
        for p in contract_package.package_papers(
            conn, package["agreement"], package["all"]
        )
    }
    assert got == {
        package["sched_p"],
        package["att_p"],
    }  # never the paper itself, never another package
    narrow = contract_package.package_papers(
        conn, package["agreement"], {package["agreement"], package["att_p"]}
    )
    assert [p["document_id"] for p in narrow] == [
        package["att_p"]
    ]  # rule 5: only papers the caller may read
    named, more = contract_package.referred_package_papers(
        conn, package["agreement"], package["all"], 10
    )
    assert (named, more) == (
        [package["sched_p"]],
        0,
    )  # the schedule itself, not its attachment (the paper names Schedule P)


def test_the_plan_of_a_contract_gives_its_named_package_papers_and_lists_them_before_the_start(
    package, monkeypatch
):
    monkeypatch.setattr(
        review_engine,
        "read_facts",
        lambda *a, **k: (open_facts(kind="contract", is_contract=True), None),
    )
    plan = review_engine.plan_for(
        db.connect(), package["agreement"], package["all"], "claude"
    )
    assert plan["project_document_ids"] == [package["sched_p"]]
    assert plan["contract_package"]["given"] == [package["sched_p"]]
    leaving = {d["id"]: d for d in plan["documents"]["leaving"]}
    assert leaving[package["sched_p"]]["why"] == review_leaving.WHY_PACKAGE
    assert package["foreign"] not in leaving
    chosen = review_engine.plan_for(
        db.connect(),
        package["agreement"],
        package["all"],
        "claude",
        project_ids=(package["att_p"],),
    )
    assert chosen["project_document_ids"] == [
        package["att_p"],
        package["sched_p"],
    ]  # the person's choice first, then the package
    hidden = review_engine.plan_for(
        db.connect(),
        package["agreement"],
        package["all"] - {package["sched_p"]},
        "claude",
    )
    assert (
        hidden["project_document_ids"] == []
    )  # a paper the caller may not read is never given


def test_a_datasheet_plan_is_given_no_package_papers(package, monkeypatch):
    monkeypatch.setattr(
        review_engine, "read_facts", lambda *a, **k: (open_facts(), None)
    )
    plan = review_engine.plan_for(
        db.connect(), package["agreement"], package["all"], "claude"
    )
    assert (
        plan["project_document_ids"] == [] and plan["contract_package"]["given"] == []
    )


# --------------------------------------------------------------------------------------------- P2 and C2: what a name is


def test_a_name_is_the_papers_own_part_a_held_schedule_a_schedule_not_held_or_a_book(
    package,
):
    conn = db.connect()
    parts = contract_package.PaperParts(conn, package["agreement"], package["all"])
    kinds = {n: parts.resolve(n) for n in ("Time for finishing", "Agreement papers", "Price (Schedule P)", "Taxes (Schedule Q)",
                                           "Taxes and Duties", "API 610", "Quality Manual")}  # fmt: skip
    assert (
        kinds["Time for finishing"].kind == contract_package.OWN
        and kinds["Time for finishing"].page == 2
    )  # a heading
    assert (
        kinds["Agreement papers"].kind == contract_package.OWN
    )  # placed by the paper in its own Sub-Article
    assert (
        kinds["Price (Schedule P)"].kind,
        kinds["Price (Schedule P)"].document_id,
    ) == (contract_package.HELD, package["sched_p"])
    assert (kinds["Taxes (Schedule Q)"].kind, kinds["Taxes (Schedule Q)"].name) == (
        contract_package.NOT_HELD,
        "Schedule Q",
    )
    assert (
        kinds["Taxes and Duties"].name == "Schedule Q"
    )  # the title the paper prints under its label is that part
    assert (
        kinds["API 610"].kind == kinds["Quality Manual"].kind == contract_package.BOOK
    )  # a real book stays a book
    assert (
        parts.not_held_name("Time for finishing") == ""
        and parts.not_held_name("Taxes (Schedule Q)") == "Schedule Q"
    )


def test_an_article_that_only_refers_to_a_book_does_not_make_it_the_papers_own_part():
    pages = [
        (
            1,
            "4.\nSAFETY\nThe Builder shall follow the Site Safety Manual referred to in Article 4 hereof at all times.\n",
        )
    ]
    assert (
        contract_package.resolve_name("Site Safety Manual", pages).kind
        == contract_package.BOOK
    )


def _rule_row(name: str):
    row = {"row_kind": "ai_engineering_check", "finding_id": "f-own", "page_section": "p.2 - Start date", "comment": "",
           "standard_reference": name, "priority": "Medium"}  # fmt: skip
    finding = {"standard_document_id": None, "standard_clause": "", "finding": "The start date is left blank in the paper.",
               "ai_rationale": "Potential, unverified: source not held, engineer to verify. The start date is blank."}  # fmt: skip
    return row, finding


def test_a_rule_check_row_naming_the_papers_own_heading_is_never_a_missing_book(
    package,
):
    ctx = {
        "run_id": "r",
        "paper_document_id": package["agreement"],
        "readable": package["all"],
        "_library": [],
    }
    row, finding = _rule_row("Time for finishing")
    p = review_points.rule_point(row, ctx, finding, {}, proof=(True, True))
    assert p["_book_missing"] is None and p["rule_ref"] is None
    assert p["reason_words"].startswith(
        "Not a rule book:"
    ) and "source not held" not in (p["action"] or "")
    assert review_points.books_not_held([], [p], []) == []
    row, finding = _rule_row("Taxes (Schedule Q)")
    q = review_points.rule_point(row, ctx, finding, {}, proof=(True, True))
    assert q["_book_missing"] == "Schedule Q" and review_points.books_not_held(
        [], [p, q], []
    ) == ["Schedule Q"]


def test_the_general_review_lists_no_own_part_as_a_book_not_held(package):
    conn = db.connect()
    got = agent_general_review._not_held_parts(conn, package["agreement"], [
        {"rule_book": "Time for finishing", "why": "cited by the paper"},
        {"rule_book": "Price (Schedule P)", "why": "cited by the paper"},
        {"rule_book": "Taxes (Schedule Q)", "why": "cited by the paper"},
        {"rule_book": "Quality Manual", "why": "cited by the paper"},
    ])  # fmt: skip
    assert [b["rule_book"] for b in got] == ["Schedule Q", "Quality Manual"]


# --------------------------------------------------------------------------------------------- C3 blanks to fill


def test_code_finds_each_page_with_blanks_and_says_what_they_are_for_never_a_contents_leader():
    found = contract_checks.blanks(AGREEMENT)
    assert sorted(found) == [1, 2, 3]
    assert {k for k, _l in found[1]} == {"date"} and {k for k, _l in found[3]} == {
        "signature"
    }
    assert [k for k, _l in found[2]] == [
        "price",
        "price",
    ]  # the leader line "..... 12" is not a blank
    results = contract_checks.check_blanks(AGREEMENT)
    assert [r.quotes[0].page for r in results] == [1, 2, 3] and all(
        r.outcome == contract_checks.ENGINEER for r in results
    )


def test_a_contract_gets_one_query_row_per_page_with_blanks_and_a_procedure_none():
    lines = agent_general_review.blank_lines("agr_1", "contract", dict(AGREEMENT))
    assert [ln["paper_page"] for ln in lines] == [1, 2, 3]
    final = [agent_general_review.finalize_line(ln) for ln in lines]
    assert all(ln["verdict_class"] == agent_general_review.CLASS_QUERY for ln in final)
    assert all(
        ln["topic"]
        == "blank to be filled before signing"
        == contract_checks.BLANK_TOPIC
        for ln in final
    )
    assert agent_general_review.blank_lines("agr_1", "procedure", dict(AGREEMENT)) == []


def test_the_general_review_adds_the_blank_rows_before_any_model_part(monkeypatch):
    from app import agent_general_parts

    calls = []

    class Fake:
        paper, kind, pages, local, lines = (
            "agr_1",
            "contract",
            dict(AGREEMENT),
            None,
            [],
        )
        add = lambda self, ln: self.lines.append(ln)  # noqa: E731
        blank_lines = agent_general_parts.GeneralRun.blank_lines

        def __getattr__(self, name):
            return lambda *a, **k: calls.append(name)

    fake = Fake()
    agent_general_parts.GeneralRun.run_all(fake)
    assert [ln["paper_page"] for ln in fake.lines] == [1, 2, 3] and calls[0] == "part1"


# --------------------------------------------------------------------------------------------- C4 quotes are full sentences


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("(herein called", False),
        ("4.", False),
        ("", False),
        ("______________________", False),
        (
            "(USD .......) as set out in Schedule P and referred to as the Price.",
            False,
        ),  # opens with a bracket
        (
            "certificate and a valid invoice by the Builder of the works.",
            False,
        ),  # starts inside a sentence, no verb
        ("The Owner shall pay the price in four stages.", True),
        ("The Builder started the work on the first day.", True),
    ],
)
def test_a_quote_is_evidence_only_when_it_is_a_full_sentence(text, ok):
    assert quote_sentence.is_full_sentence(text) is ok


def test_on_a_general_paper_a_fragment_quote_becomes_no_quote_and_a_datasheet_is_untouched():
    frag = {
        "paper_quote": "(herein called",
        "paper_quote_note": "x",
        "paper_value": None,
    }
    whole = {
        "paper_quote": "The Owner shall pay the price in four stages.",
        "paper_quote_note": "x",
    }
    review_points_service.sentence_quotes([frag, whole], "contract")
    assert (
        frag["paper_quote"] is None
        and frag["paper_quote_note"] == quote_sentence.NO_SENTENCE
        and frag["paper_quote_refused"]
    )
    assert whole["paper_quote"] == "The Owner shall pay the price in four stages."
    cell = {"paper_quote": "50 m3/h", "paper_quote_note": "x"}
    review_points_service.sentence_quotes([cell], "datasheet")
    assert cell["paper_quote"] == "50 m3/h"


def test_the_general_reviews_own_file_prints_no_fragment_as_what_the_paper_states():
    line = {"part": 5, "verdict_class": agent_general_review.CLASS_NOTE, "subkind": agent_general_review.SUB_ENGINEERING,
            "text": "an invented note", "quotes_verified_by_code": True, "quote_a": {"text": "4.", "page": 2}}  # fmt: skip
    shows = agent_general_crs.comment_of(line, crs_ai_words.STATUS_AI).split("\n")[1]
    assert '"4."' not in shows and shows.startswith(agent_general_crs.NO_QUOTE)


def test_classification_role_is_what_marks_a_contract_for_the_package(package):
    classification.set_role(package["att_p"], "SPECIFICATION")
    got = {
        p["document_id"]
        for p in contract_package.package_papers(
            db.connect(), package["agreement"], package["all"]
        )
    }
    assert got == {
        package["sched_p"]
    }  # a specification of the same number is not a contract paper of the package
