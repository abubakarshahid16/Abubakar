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
from tests.test_p3_review_jobs import (  # noqa: F401 - fixtures
    _user,
    temp_storage,
    world,
)

NUMBER = "QX-7781-ZZ"  # invented
OTHER_NUMBER = "QX-9999-YY"  # invented: another package
AGREEMENT = [
    (1, f"Invented Works Programme     CONTRACT No. {NUMBER}\nForm of Agreement\nPage 1 of 3\nRev 04\n"
        "1.\nPARTIES\nThis Agreement is made on ______ day of ________, 2031.\n"
        "1.1\nThe parties to this Agreement are named on this page.\n"
        'SCHEDULE "P"  Price and Payment\nSCHEDULE "Q"\nTaxes and Duties\n'),
    (2, f"Invented Works Programme     CONTRACT No. {NUMBER}\n2.\nWORK START AND TIME FOR FINISHING\n"
        "The Builder shall start the work on the date stated in Schedule P.\n"
        "The Agreement Papers listed in Sub-Article 1.1 of this Agreement form the whole agreement.\n"
        "3.\nPAYMENT\nThe Owner shall pay the sum of ____________ Dollars (USD ..........) as set out in SCHEDULE P.\n"
        "Contents of the schedules ..................... 12\n"),
    (3, f"Invented Works Programme     CONTRACT No. {NUMBER}\nSignature: ____________\nName: ____________\n"),
]  # fmt: skip
SCHEDULE_P = [(1, f"Invented Works Programme     CONTRACT No. {NUMBER}\nSCHEDULE “P” - Price and Payment\nPage 1 of 2\n"
                  "The Owner shall pay the price in the stages set out below for the whole of the work.\n")]  # fmt: skip
ATTACHMENT_P = [(1, f"Invented Works Programme     CONTRACT No. {NUMBER}\nSCHEDULE “P” - Attachment I - Rate Sheet\n"
                    "The rates below apply to all work ordered under the agreement and its schedules.\n")]  # fmt: skip
FOREIGN_P = [(1, f"Another Invented Programme     CONTRACT No. {OTHER_NUMBER}\nSCHEDULE “P” - Price\n"
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
        "CONTRACT No.",
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
        head["document_number"] == f"{NUMBER} (CONTRACT No.)"
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
        ("(USD .......) as set out in Schedule P and referred to as the Price.", False),  # opens with a bracket
        ("certificate and a valid invoice by the Builder of the works.", False),  # starts inside a sentence
        ("The Builder shall start the work on the date stated in the", False),  # stops on a word that needs more
        ("The Owner shall pay the sum (herein called", False),  # stops inside an open bracket
        ("The Owner shall pay the price in four stages.", True),
        ("The Builder started the work on the first day.", True),
        ("Retention 10% of the price", True),  # a one-line clause that states a value
    ],
)  # fmt: skip
def test_a_quote_is_evidence_only_when_it_is_a_full_sentence_or_a_value_clause(
    text, ok
):
    assert quote_sentence.is_evidence(text) is ok


def _general_point(quote):
    return {
        "source": review_points.SOURCE_AI_REVIEW,
        "_line": {"general": True},
        "paper_quote": quote,
        "paper_quote_note": "x",
    }


def test_on_a_general_paper_a_fragment_keeps_its_words_beside_the_mark_and_no_compared_value_is_touched():
    frag, whole = (
        _general_point("(herein called"),
        _general_point("The Owner shall pay the price in four stages."),
    )
    compared = {"source": review_points.SOURCE_RULE_CHECK, "_row": {"row_kind": "datasheet_check"}, "paper_quote": "95",
                "paper_quote_note": "x"}  # fmt: skip
    drafted = {"source": review_points.SOURCE_RULE_CHECK, "_row": {"row_kind": "ai_engineering_check"}, "paper_quote": "4.",
               "paper_quote_note": "x"}  # fmt: skip
    review_points_service.sentence_quotes([frag, whole, compared, drafted], "contract")
    assert frag["paper_quote"] is None and frag["paper_quote_refused"]
    assert (
        frag["paper_quote_note"]
        == 'No quote: the paper\'s words "(herein called" are not a full sentence.'
    )
    assert whole["paper_quote"] == "The Owner shall pay the price in four stages."
    assert (
        compared["paper_quote"] == "95"
    )  # a value code compared keeps its paper value
    # a rule-check row's quote with no value must pass the same test: "4." is a clause number, not a value (lead, PR #1881 round 2)
    assert drafted["paper_quote"] is None and drafted["paper_quote_note"].startswith(
        'No quote: the paper\'s words "4."'
    )
    cell = _general_point("50 m3")
    review_points_service.sentence_quotes([cell], "datasheet")
    assert cell["paper_quote"] == "50 m3"


def test_the_page_and_the_one_crs_run_the_sentence_test_on_the_assembled_points(
    package, monkeypatch
):
    from app import access

    frag = {
        **_general_point("(herein called"),
        "id": "ai:r:G-001",
        "rank": 4,
        "tile": "question",
        "name": "a point",
    }
    monkeypatch.setattr(review_points_service, "runs_of_paper", lambda *a: (None, "r"))
    monkeypatch.setattr(review_points, "ai_points_of_run", lambda *a: ([frag], []))
    monkeypatch.setattr(review_points_service, "_paper_kind", lambda *a: "contract")
    monkeypatch.setattr(
        review_points_service.settings, "ai_review_calculator_enabled", False
    )
    try:
        review_points_service._assemble(
            package["agreement"], access.unrestricted_scope()
        )
    except Exception:  # noqa: BLE001 - later steps of the listing need a real run; the point was already decided in place
        pass
    assert frag["paper_quote"] is None and frag["paper_quote_refused"]


def test_the_general_reviews_own_file_prints_no_fragment_as_evidence_but_keeps_its_words():
    line = {"part": 5, "verdict_class": agent_general_review.CLASS_NOTE, "subkind": agent_general_review.SUB_ENGINEERING,
            "text": "an invented note", "quotes_verified_by_code": True, "quote_a": {"text": "4.", "page": 2}}  # fmt: skip
    shows = agent_general_crs.comment_of(line, crs_ai_words.STATUS_AI).split("\n")[1]
    assert not shows.startswith("The paper states")
    assert shows.startswith(
        'No quote: the paper\'s words "4." are not a full sentence (page 2).'
    )


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


# --------------------------------------------------------------------------------------------- lead review items 1, 2, 3, 5, 6, 7


def test_every_labelled_part_the_contract_cites_is_listed_held_or_not_held(package):
    conn = db.connect()
    assert contract_package.cited_parts(conn, package["agreement"]) == {
        "held": ["Schedule P"],
        "not_held": ["Schedule Q"],
    }
    parts = contract_package.PaperParts(conn, package["agreement"], package["all"])
    assert parts.not_held_list(conn, ["Time for finishing"], "contract") == [
        "Schedule Q"
    ]  # cited by no row, still listed
    assert parts.not_held_list(conn, [], "procedure") == []
    got = agent_general_review._not_held_parts(
        conn, package["agreement"], [], "contract"
    )
    assert [b["rule_book"] for b in got] == ["Schedule Q"]


def test_a_spaced_cover_number_is_read_whole_and_two_packages_sharing_its_first_group_are_apart(
    temp_storage,  # noqa: F811
):
    first = [
        (
            1,
            "Invented Works     Contract No. 6601 000111\nThe Owner shall pay the price.\n",
        )
    ]
    second = [
        (
            1,
            "Invented Works     Contract No. 6601 000222\nThe Owner shall pay the price.\n",
        )
    ]
    assert contract_package.cover_id(first).number == "6601 000111"
    _paper("sp_1", first, n=91)
    _paper("sp_2", second, n=92)
    assert contract_package.package_papers(db.connect(), "sp_1", {"sp_1", "sp_2"}) == []


def test_only_a_document_or_contract_number_and_a_revision_value_are_read_from_the_cover():
    other = contract_package.cover_id(
        [(1, "Purchase Order No. PO-4411\nDrawing No. DW-7781\nRevision a\n")]
    )
    assert other.number is None and other.revision is None
    doc = contract_package.cover_id(
        [(1, "Drawing No. DW-7781\nDoc. No. QX-1-22\nRev. B\n")]
    )
    assert (doc.number, doc.revision) == ("QX-1-22", "B")


def test_an_entry_of_the_papers_reference_list_is_never_its_own_part():
    pages = [(1, "1.\nSCOPE\nThis procedure covers the testing of the invented pumps on site.\n"
                 "2.\nREFERENCES\n2.1 Site Test Handbook\n2.2 Pump Care Guide\n"
                 "3.\nTESTING\nThe tester shall run the pump for one hour at full load.\n")]  # fmt: skip
    assert (
        contract_package.resolve_name("Site Test Handbook", pages).kind
        == contract_package.BOOK
    )
    assert contract_package.resolve_name("Testing", pages).kind == contract_package.OWN
    placed = [
        (
            1,
            "1.\nSCOPE\nThe Site Manual set out in Clause 9 of this procedure applies to the testers.\n",
        )
    ]
    assert (
        contract_package.resolve_name("Site Manual", placed).kind
        == contract_package.BOOK
    )  # Clause 9 is not in the paper


def test_separators_contents_leaders_and_tick_boxes_are_not_blanks():
    pages = [(1, "CONTENTS\n1.\nTERMS\n" + "_" * 70 + "\nThe schedules ......................\n12\n"
                 "Annex list ........ iv\nPrice terms ........ Page 3\nAccepted [ ] Refused [ ]\nName: ________\n")]  # fmt: skip
    found = contract_checks.blanks(pages)
    assert [k for k, _l in found[1]] == ["signature"]


def test_a_dotted_blank_before_a_page_footer_and_a_long_rule_under_a_label_are_blanks():
    pages = [(1, "The Owner shall pay the sum of ......................\n12\n"
                 "Witness:\n" + "_" * 70 + "\n")]  # fmt: skip
    found = contract_checks.blanks(pages)
    assert (
        len(found[1]) == 2
    )  # not a contents page, so "12" is a footer; the long rule has its label above


def test_the_start_stores_the_plans_package_papers_with_the_run(package, monkeypatch):
    from app import review_engine_start

    monkeypatch.setattr(
        review_engine,
        "read_facts",
        lambda *a, **k: (open_facts(kind="contract", is_contract=True), None),
    )
    plan = review_engine.plan_for(
        db.connect(), package["agreement"], package["all"], "claude"
    )
    shown = tuple(d["id"] for d in plan["documents"]["leaving"])
    _user("adm", list(package["all"]), admin=True)
    run_id, stored = review_engine_start.start(
        package["agreement"], package["all"], "adm", "claude", shown_document_ids=shown
    )
    assert stored["project_document_ids"] == [package["sched_p"]]
    row = (
        db.connect()
        .execute(
            "SELECT plan_json FROM review_engine_choice WHERE run_id = ?", (run_id,)
        )
        .fetchone()
    )
    assert package["sched_p"] in row[0]


def test_automatic_lists_no_package_paper_as_leaving(package, monkeypatch):
    monkeypatch.setattr(
        review_engine,
        "read_facts",
        lambda *a, **k: (open_facts(kind="contract", is_contract=True), None),
    )
    plan = review_engine.plan_for(
        db.connect(), package["agreement"], package["all"], "automatic"
    )
    leaving = {d["id"] for d in plan["documents"]["leaving"]}
    assert (
        package["sched_p"] not in leaving and package["agreement"] not in leaving
    )  # Automatic never sends a contract


@pytest.mark.parametrize(
    ("text", "value"),
    [("80", True), ("< 15", True), ("10 barg", True), ("6%", True), ("10-20", True), ("316L", True), ("WCB", True),
     ("4.", False), ("2.1.", False), ("(herein called", False), ("2.1 Site Test Handbook", False), ("", False)],
)  # fmt: skip
def test_a_quote_holds_a_value_only_as_a_figure_unit_comparator_range_or_code(
    text, value
):
    assert quote_sentence.holds_value(text) is value


def test_a_rule_check_quote_that_holds_a_value_is_kept_and_one_without_is_refused_with_its_page():
    def row(quote):
        return {"source": review_points.SOURCE_RULE_CHECK, "_row": {"row_kind": "ai_engineering_check"}, "paper_quote": quote,
                "paper_quote_note": "x", "page": 3}  # fmt: skip

    kept, comparator, frag = row("80"), row("< 15"), row("(herein called")
    review_points_service.sentence_quotes([kept, comparator, frag], "procedure")
    assert kept["paper_quote"] == "80" and comparator["paper_quote"] == "< 15"
    assert frag["paper_quote"] is None
    assert (
        frag["paper_quote_note"]
        == 'No quote: the paper\'s words "(herein called" are not a full sentence (page 3).'
    )


def test_sheet_one_prefers_the_papers_own_document_number_to_a_contract_number(package):
    conn = db.connect()
    _paper(
        "ds_1",
        [
            (
                1,
                "Contract No. QX-55-01\nDoc. No. DS-0007-A\nRev 2\nAn invented sheet of values.\n",
            )
        ],
        n=93,
    )
    assert (
        crs_ai_header.with_cover(conn, "ds_1", {"document_number": "", "revision": ""})[
            "document_number"
        ]
        == "DS-0007-A"
    )
    _paper("ds_2", [(1, "Contract No. QX-55-01\nAn invented sheet of values.\n")], n=94)
    held = crs_ai_header.with_cover(
        conn, "ds_2", {"document_number": "DS-0008-B", "revision": ""}
    )
    assert (
        held["document_number"] == "DS-0008-B"
    )  # the number held for the paper, never the contract's
    assert (
        contract_package.cover_id(
            [(1, "Doc. No. DS-1\nContract No. QX-55-01\n")]
        ).number
        == "QX-55-01"
    )  # the package key


def test_a_rule_check_rows_stored_passage_without_a_value_is_refused_and_a_value_is_kept():
    def row(value):
        return {"source": review_points.SOURCE_RULE_CHECK, "_row": {"row_kind": "ai_engineering_check"}, "paper_quote": None,
                "paper_value": value, "paper_value_page": 3, "paper_quote_note": "x"}  # fmt: skip

    frag, value = (
        row("(USD ....) as set out in the price schedule (herein called"),
        row("6%"),
    )
    review_points_service.sentence_quotes([frag, value], "contract")
    assert frag["paper_value"] is None and frag["paper_quote_note"].endswith(
        "are not a full sentence (page 3)."
    )
    assert value["paper_value"] == "6%"


@pytest.mark.parametrize(
    "line",
    [
        "Document No. ZZ-100-01 17 Nov 2026",
        "Doc No: ZZ-100 2 of 10",
        "Contract No. 12345 2026",
        "Contract No. 6600 045321 2 of 4",
    ],
)
def test_a_cover_number_never_takes_a_date_a_page_count_or_a_year(line):
    want = {"Document No. ZZ-100-01 17 Nov 2026": "ZZ-100-01", "Doc No: ZZ-100 2 of 10": "ZZ-100",
            "Contract No. 12345 2026": "12345", "Contract No. 6600 045321 2 of 4": "6600 045321"}  # fmt: skip
    assert contract_package.cover_id([(1, line)]).number == want[line]


@pytest.mark.parametrize(
    "text",
    [
        "2.1 Site Conditions",
        "Section 12 General",
        "Page 3 of 8",
        "Article 4 of the",
        "and 10 days after",
    ],
)
def test_a_clause_page_or_article_number_or_a_plain_word_is_never_a_value(text):
    assert not quote_sentence.holds_value(text) and not quote_sentence.is_value_clause(
        text
    )


def test_both_refused_passages_keep_their_words_and_a_held_value_is_still_shown():
    from app import crs_one

    def row(quote, value):
        return {"source": review_points.SOURCE_RULE_CHECK, "_row": {"row_kind": "ai_engineering_check"}, "paper_quote": quote,
                "page": 3, "paper_value": value, "paper_value_page": 4, "paper_quote_note": "x"}  # fmt: skip

    both, kept = (
        row("(herein called", "and the other part"),
        row("(herein called", "Set pressure 10 barg"),
    )
    review_points_service.sentence_quotes([both, kept], "contract")
    assert both["paper_quote_note"] == (
        'No quote: the paper\'s words "(herein called" (page 3) and "and the other part" (page 4) are not full sentences.'
    )
    assert kept["paper_value"] == "Set pressure 10 barg"
    shown = crs_one.paper_shows(kept)
    assert (
        shown.startswith('No quote: the paper\'s words "(herein called"')
        and '"Set pressure 10 barg" (as stored, page 4' in shown
    )
