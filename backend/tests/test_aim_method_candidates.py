"""`aim_review.candidates`: plan time, library metadata only. No model call, no socket, no write; a book the caller may not read
is counted, never named; a saved checklist decides by itself; at most 20 books."""

from __future__ import annotations

import pytest

from app import aim_review
from app.aim_review import library as L
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    BOOK_C,
    PAPER,
    MemoryStore,
    open_aim_db,
)


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


ALL = frozenset({PAPER, BOOK_A, BOOK_B, BOOK_C})


@pytest.fixture
def no_model(monkeypatch):
    """Any attempt to reach a model or the Claude socket fails the test."""
    from app import agent_claude, reader_transport

    def refuse(*_a, **_k):
        raise AssertionError("candidates asked a model")

    monkeypatch.setattr(reader_transport, "transport", refuse)
    monkeypatch.setattr(agent_claude, "_request", refuse)
    monkeypatch.setattr(agent_claude, "_send_once", refuse)


@pytest.fixture
def kind_datasheet(monkeypatch):
    from app import agent_review_kind

    monkeypatch.setattr(
        agent_review_kind,
        "read_kind",
        lambda conn, doc: {
            "kind": "datasheet",
            "known": True,
            "method": "title_cue",
            "guess": False,
        },
    )
    monkeypatch.setattr(
        agent_review_kind, "read_equipment", lambda doc, allowed: (None, None)
    )


def _state(conn):
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
    ]
    return [
        (t, conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]) for t in tables
    ]


def test_candidates_lists_the_books_with_rules_of_the_kind(
    aim_db, no_model, kind_datasheet
):
    c = aim_review.candidates(aim_db, PAPER, ALL, MemoryStore())
    assert c.kind == "datasheet" and c.equipment_type is None
    assert {b["id"] for b in c.books} == {BOOK_A, BOOK_B, BOOK_C}
    assert all(b["why"] == L.WHY_RULES for b in c.books)
    assert c.unreadable == 0
    assert PAPER not in {b["id"] for b in c.books}


def test_candidates_makes_no_model_call_and_no_write(aim_db, no_model, kind_datasheet):
    before, changes = _state(aim_db), aim_db.total_changes
    aim_review.candidates(aim_db, PAPER, ALL, MemoryStore())
    assert _state(aim_db) == before and aim_db.total_changes == changes


def test_a_book_the_caller_may_not_read_is_counted_never_named(
    aim_db, no_model, kind_datasheet
):
    c = aim_review.candidates(aim_db, PAPER, frozenset({PAPER, BOOK_A}), MemoryStore())
    assert [b["id"] for b in c.books] == [BOOK_A]
    assert c.unreadable == 2
    text = repr(c)
    assert BOOK_B not in text and BOOK_C not in text
    assert "QX-STD-202" not in text and "QX-STD-303" not in text


def test_a_saved_checklist_decides_the_books(aim_db, no_model, monkeypatch):
    from app import agent_review_kind

    monkeypatch.setattr(
        agent_review_kind,
        "read_kind",
        lambda conn, doc: {
            "kind": "datasheet",
            "known": True,
            "method": "title_cue",
            "guess": False,
        },
    )
    type_id = sorted(L.type_ids())[0]
    monkeypatch.setattr(
        agent_review_kind,
        "read_equipment",
        lambda doc, allowed: (type_id, "classification"),
    )
    store = MemoryStore()
    key = f"datasheet__{type_id}"
    store.put(
        key,
        {
            "built_from": "standards only, no paper",
            "items": [],
            "books": [{"alias": "B01", "book": BOOK_B}],
        },
        run_id="r0",
        usd=0.0,
    )
    c = aim_review.candidates(aim_db, PAPER, ALL, store)
    assert c.checklist_key == key and c.checklist_saved
    assert [(b["id"], b["why"]) for b in c.books] == [(BOOK_B, L.WHY_SAVED)]


def test_an_unknown_kind_offers_no_rules_of_a_kind(aim_db, no_model, monkeypatch):
    from app import agent_review_kind

    monkeypatch.setattr(
        agent_review_kind,
        "read_kind",
        lambda conn, doc: {
            "kind": None,
            "known": False,
            "method": "no_cue",
            "guess": False,
        },
    )
    c = aim_review.candidates(aim_db, PAPER, ALL, MemoryStore())
    assert (
        c.kind is None
        and c.books == []
        and c.checklist_key is None
        and not c.checklist_saved
    )


def test_books_an_earlier_review_wanted_are_listed_first(
    aim_db, no_model, kind_datasheet
):
    c = aim_review.candidates(
        aim_db, PAPER, ALL, MemoryStore(), earlier_unlisted=frozenset({BOOK_C})
    )
    assert c.books[0] == {"id": BOOK_C, "why": L.WHY_LAST}


def test_at_most_twenty_books(aim_db, no_model, kind_datasheet, monkeypatch):
    many = [
        {
            "book": f"doc_many{i:02d}",
            "identifier": f"QX-{i}",
            "committee": "",
            "rules": 1,
            "tagged": 0,
            "subjects": [],
        }
        for i in range(30)
    ]
    monkeypatch.setattr(L, "catalog", lambda by_id, pool, top_subjects=6: many)
    monkeypatch.setattr(L, "role_applies", lambda e, k: True)
    monkeypatch.setattr(
        L,
        "library",
        lambda conn, exclude=frozenset(), within=None: [
            {"id": m["book"], "filename": f"ISO 9{i:04d}.pdf"}
            for i, m in enumerate(many)
        ],  # public-family books: a company standard is offered only when cited or table-named
    )
    allowed = frozenset(m["book"] for m in many)
    c = aim_review.candidates(aim_db, PAPER, allowed, MemoryStore())
    assert len(c.books) == L.MAX_CANDIDATES == 20


def test_a_cited_book_is_found_by_its_identifier(
    aim_db, no_model, kind_datasheet, monkeypatch
):
    from app import standard_ids

    monkeypatch.setattr(
        standard_ids, "cited_standards", lambda text: ["ISO 99202", "ISO 99999"]
    )  # the helper books are invented public-family books
    c = aim_review.candidates(aim_db, PAPER, ALL, MemoryStore())
    whys = {b["id"]: b["why"] for b in c.books}
    assert whys[BOOK_B] == L.WHY_CITED
    assert {"name": "ISO 99999", "why": f"{L.WHY_CITED}; not held"} in c.not_held


def test_the_stored_kind_spelling_is_the_methods():
    assert L.method_kind("test_record") == "test record"
    assert L.method_kind("transmittal") == "other"
    assert L.method_kind(None) is None
    assert L.method_kind("datasheet") == "datasheet"


# ---- a COMPANY standard (an owner's own rule book) is offered only when the paper cites it or a table names it ----------------

COMPANY = "doc_aimcompany1"
#: The recorded role of the client's OWN standards (the owner's choice at upload), and a role that is not that.
OWN, OTHER = "COMPANY_STANDARD", "REFERENCE_DOCUMENT"


def _company_book(conn, role: str = OTHER):
    """An invented non-public book (prefix "ZQ") holding rules labelled for the kind. By default its recorded role is NOT the
    client's own standard (a reference document): used only when the paper cites it. With role OWN it is the client's own."""
    import json

    from tests.test_aim_method_helpers import _doc, _hex

    with conn:
        _doc(
            conn,
            COMPANY,
            "ZQ-ENG-501.pdf",
            role,
            {3: "Section heading\n2.1 The item shall be tagged.\n"},
        )
        conn.execute(
            "INSERT INTO standard_requirements (id, standard_document_id, clause, page, requirement_text, source_text,"
            " created_at, updated_at) VALUES ('req_zq', ?, '2.1', 3, 'The item shall be tagged.', 'The item shall be tagged.',"
            " 'x', 'x')",
            (COMPANY,),
        )
        conn.execute(
            "INSERT INTO rule_label (source, rule_ref, paper_kind, state, a_model, a_prompt, a_answer_sha256, b_model, b_prompt,"
            " b_answer_sha256, reading_json, quote_page, quote_sha256, labelled_at) VALUES ('requirement', 'req_zq', 'datasheet',"
            " 'ai_approved', 'model-a', 'p', ?, 'model-b', 'p', ?, ?, 3, ?, 'x')",
            (_hex("a"), _hex("b"), json.dumps({"subject": "tagging"}), _hex("q")),
        )


def test_an_own_standard_with_an_invented_prefix_is_usable_and_listed_by_its_reason_uncited(
    aim_db, no_model, kind_datasheet
):
    """The owner (18 Nov 2026): the client is a joint operation of its owner companies, so every book recorded as a company
    standard is the client's OWN and applies to every paper. The recorded role decides, never a name shape."""
    _company_book(aim_db, role=OWN)
    c = aim_review.candidates(aim_db, PAPER, ALL | {COMPANY}, MemoryStore())
    whys = {b["id"]: b["why"] for b in c.books}
    assert (
        whys[COMPANY] == L.WHY_RULES and BOOK_A in whys
    )  # not cited, still listed by its own reason
    assert not L.is_public({"filename": "ZQ-ENG-501.pdf"}) and L.is_own(
        {"document_role": OWN}
    )


def test_a_non_public_book_without_the_role_that_the_paper_does_not_cite_is_not_usable(
    aim_db, no_model, kind_datasheet
):
    _company_book(
        aim_db
    )  # recorded as a reference document, not the client's own standard
    c = aim_review.candidates(aim_db, PAPER, ALL | {COMPANY}, MemoryStore())
    ids = [b["id"] for b in c.books]
    assert COMPANY not in ids and BOOK_A in ids  # public books unaffected


def test_a_document_of_another_role_is_never_a_rule_book_even_when_the_paper_cites_it(
    aim_db, no_model, kind_datasheet, monkeypatch
):
    """Fix check 961f7126, N2: the recorded role decides first; a citation by file name never makes a reference document (or a
    contract) a rule book, and a public-looking file name never makes a contract one."""
    from app import standard_ids

    _company_book(aim_db)
    monkeypatch.setattr(standard_ids, "cited_standards", lambda text: ["ZQ-ENG-501"])
    assert L.cited_company(aim_db, PAPER) == frozenset()
    c = aim_review.candidates(aim_db, PAPER, ALL | {COMPANY}, MemoryStore())
    assert COMPANY not in [b["id"] for b in c.books]
    contract = {
        "id": "x",
        "filename": "ISO 99999 purchase contract.pdf",
        "document_role": "CONTRACT_DOCUMENT",
    }
    assert L.is_public(contract) and not L.is_rule_book(contract)
    assert L.is_rule_book(
        {"id": "y", "filename": "ISO 99101.pdf", "document_role": None}
    )  # an unroled public standard
    assert not L.is_rule_book(
        {"id": "z", "filename": "ZQ-ENG-501.pdf", "document_role": None}
    )  # unroled, not public


def test_an_own_standard_is_never_in_the_cited_key_set(
    aim_db, no_model, kind_datasheet, monkeypatch
):
    from app import standard_ids

    _company_book(aim_db, role=OWN)
    monkeypatch.setattr(standard_ids, "cited_standards", lambda text: ["ZQ-ENG-501"])
    assert (
        L.cited_company(aim_db, PAPER) == frozenset()
    )  # the cited key stays for cited books that are not the client's own


def test_s2s_catalog_holds_an_own_book_never_another_role_even_cited(aim_db, no_model):
    from app.aim_review import checklist as CL

    ident = {"kind": "datasheet", "equipment_type": None}
    listed = frozenset({BOOK_A, BOOK_B, COMPANY})
    _company_book(aim_db)
    for cited in (frozenset(), frozenset({COMPANY})):
        cat, *_ = CL._catalog(
            aim_db, PAPER, ident, listed, {"listed": {}}, lambda b: None, cited
        )
        assert COMPANY not in {c["book"] for c in cat} and BOOK_A in {
            c["book"] for c in cat
        }
    with aim_db:
        aim_db.execute(
            "UPDATE document_classification SET document_role = ? WHERE document_id = ?",
            (OWN, COMPANY),
        )
    cat, *_ = CL._catalog(aim_db, PAPER, ident, listed, {"listed": {}}, lambda b: None)
    assert COMPANY in {c["book"] for c in cat}  # the client's own: in, uncited


def test_g3_lists_an_own_books_items_uncited_and_another_only_when_cited(aim_db):
    from app.aim_review import always as A
    from app.aim_review import steps as S

    _company_book(aim_db)
    checklist = {
        "books": [{"alias": "B01", "book": COMPANY, "identifier": "ZQ-ENG-501"}],
        "items": [{"id": "C001", "book": "B01", "source": S.HELD, "topic": "tagging", "what_to_check": "x", "paper_fields": []}],
    }  # fmt: skip
    shown = frozenset({COMPANY})
    g3 = next(
        it for it in A.items(aim_db, {}, checklist, shown, {}) if it["id"] == "G3"
    )
    assert g3["carries"] == []  # not own, not cited
    with aim_db:
        aim_db.execute(
            "UPDATE document_classification SET document_role = ? WHERE document_id = ?",
            (OWN, COMPANY),
        )
    g3 = next(
        it for it in A.items(aim_db, {}, checklist, shown, {}) if it["id"] == "G3"
    )
    assert g3["carries"] == [COMPANY]


def test_an_own_standard_is_never_not_cited(aim_db):
    _company_book(aim_db, role=OWN)
    assert L.not_offered_company(aim_db, PAPER, {COMPANY}) == frozenset()
    with aim_db:
        aim_db.execute(
            "UPDATE document_classification SET document_role = ? WHERE document_id = ?",
            (OTHER, COMPANY),
        )
    assert L.not_offered_company(aim_db, PAPER, {COMPANY}) == frozenset({COMPANY})


def test_the_online_search_sends_only_public_standard_names():
    """Fix check 961f7126, N5: with not-held names now listed whatever their shape, the online search still sends only a name
    from the app's own table of public standards (`known_public_name`): never a company name, a file name or a paper's words."""
    from app import standards_web_search as W

    for name in (
        "ZQ-ENG-501",
        "97-ZQ-707",
        "ISO 99999 purchase contract of the invented unit",
        "the invented unit",
    ):
        assert W.known_public_name(name) is None, name
    known = W.known_names()
    assert known and all(W.known_public_name(k) == k for k in known[:5])
    assert all(
        L.is_public_name(k) for k in known
    )  # every name that may leave is a public publisher's


def test_a_book_gone_from_the_library_since_the_checklist_was_saved_is_not_usable(
    aim_db,
):
    """Fix check a098e8f8, N3: a saved checklist's book re-roled to a submittal (so no longer in the library) is not used."""
    _company_book(aim_db, role=OWN)
    assert L.not_offered_company(aim_db, PAPER, {COMPANY}) == frozenset()
    with aim_db:
        aim_db.execute(
            "UPDATE document_classification SET document_role = ? WHERE document_id = ?",
            ("CONTRACTOR_SUBMITTAL", COMPANY),
        )
    assert L.not_offered_company(aim_db, PAPER, {COMPANY}) == frozenset({COMPANY})
    assert L.not_offered_company(aim_db, PAPER, {"doc_never_held"}) == frozenset(
        {"doc_never_held"}
    )
