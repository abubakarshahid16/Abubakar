"""What a technical query's FORM cites is looked up first (the owner's faults of 26 Nov 2026, fault 4; builders A and C, one module,
`technical_query_cited`). Invented contracts and forms; no model, no network (the general search and the reranker are stand-ins)."""

from __future__ import annotations

from app import db
from app import technical_query_cited as CI
from app import technical_query_contracts as C
from tests.test_tq_g_feature_off import (  # noqa: F401 - helpers, fixture
    hold_contract,
    on,
    storage,
)

CLAUSE = "4.2.1 Invented Lining\nThe invented lining shall be two coats of invented resin.\nEach coat shall cure for one invented day.\n"
OTHER = (
    "4.2.2 Invented Flushing\nThe invented line shall be flushed with invented water.\n"
)
CONTENTS = (
    "Contents\n4.2.1 Invented Lining ........ 7\n4.2.2 Invented Flushing ........ 8\n"
)
SCHEDULE_B = "SCHEDULE B\nINVENTED TECHNICAL SCOPE\n1 Scope\n"


def _page(doc, page_no, text):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,0,1)",
            (doc, page_no, text, len(text)),
        )


def _hold(doc, pages: dict[int, str], filename="contract.pdf"):
    hold_contract(doc, filename)
    for n, text in pages.items():
        _page(doc, n, text)


def _reranker(monkeypatch, score=None):
    monkeypatch.setattr(
        "app.reranker.rerank",
        lambda q, passages, batch=None: (
            [] if score is None else [(i, score) for i, _ in passages]
        ),
    )


# ---- 1-2 where the form cites, and what (A)


def test_only_the_forms_reference_lines_are_read_never_its_procedure_text():
    """Measured on the stored forms: the real citations stood in the references block and the numbered REF entries; the procedure
    paragraph ("in accordance with sub clause N of Schedule A") is the form's own text, not the query's subject."""
    form = ("Invented CFC form\nCONTRACTOR submits in accordance with sub clause 11.2.2 of SCHEDULE A of Contract No. ZQ-1.\n"
            "| Documents affected: | REF.1 INVENTED SCOPE SCHEDULE B \u2013 ATTACHMENT V, Rev06, Section 7.2\n"
            "References:\nSchedule C, clause 4.2\n\nQuestion: please confirm the invented lining.")  # fmt: skip
    assert CI.reference_lines([form]) == [
        "| Documents affected: | REF.1 INVENTED SCOPE SCHEDULE B \u2013 ATTACHMENT V, Rev06, Section 7.2",
        "Schedule C, clause 4.2",
    ]
    assert CI.cited([form]) == [
        (
            (("attachment", "V"), ("schedule", "B")),
            "7.2",
        ),  # a lower part belongs to the higher part named before it
        ((("schedule", "C"), None), "4.2"),
    ]


def test_a_standard_on_the_line_gives_no_clause_and_a_clause_with_no_part_has_none():
    assert CI.cited(["REF.1 Schedule C, see API 610 clause 6.1"]) == [
        ((("schedule", "C"), None), None)
    ]
    assert CI.cited(["REF.2 Invented study, clause 4.2.1"]) == [(None, "4.2.1")]
    assert CI.titles(
        ["REF.2 Invented design basis, Section 7.2 Invented Process Design"]
    ) == {"7.2": {"invented", "process", "design"}}
    assert (
        CI.cited(
            ["An invented question with no reference line, clause 4.2.1 of Schedule B"]
        )
        == []
    )
    many = "\n".join(f"REF.{n} clause {n}.1" for n in range(1, 12))
    assert len(CI.cited([many])) == CI.MAX_CITED


# ---- 3 which contract (A)


def test_a_named_part_is_the_contract_whose_page_one_heading_says_so_and_of_two_the_higher_revision(
    monkeypatch,
):
    on(monkeypatch)
    _hold(
        "con-b", {1: SCHEDULE_B, 2: CLAUSE}, "invented-file-name.pdf"
    )  # the file name says nothing; the heading does
    _hold("con-a", {1: "SCHEDULE A\nINVENTED AGREEMENT\n", 2: CLAUSE})
    assert CI.which(["con-a", "con-b"], (("schedule", "B"), None)) == ["con-b"]
    _hold("con-b2", {1: SCHEDULE_B, 2: CLAUSE})
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET revision = '1' WHERE document_id = 'con-b'"
        )
        conn.execute(
            "UPDATE document_classification SET revision = '2' WHERE document_id = 'con-b2'"
        )
    assert CI.which(["con-a", "con-b", "con-b2"], (("schedule", "B"), None)) == [
        "con-b2"
    ]


# ---- 4 the clause in a part (C)


def test_a_part_holds_the_clause_with_its_own_text_not_its_contents_line():
    got = CI.find_clause(
        [(1, CONTENTS), (7, "Invented header\n" + CLAUSE + OTHER)], "4.2.1"
    )
    assert got["page"] == 7 and got["heading"] == "4.2.1 Invented Lining"
    assert (
        got["text"].startswith("4.2.1 Invented Lining\nThe invented lining")
        and "flushed" not in got["text"]
    )
    assert got["shortened"] is False
    assert (
        CI.find_clause([(1, CONTENTS)], "4.2.1") is None
    )  # a contents line is not the clause
    assert (
        CI.find_clause([(1, "4.2.1 Invented Lining\n")], "4.2.1") is None
    )  # a heading alone is not the clause
    assert CI.find_clause([(7, CLAUSE)], "4.2") is None  # 4.2 is not 4.2.1


def test_a_long_clause_is_cut_at_a_line_and_the_cut_is_said():
    long = "9.3 Invented Payment\n" + "".join(
        f"Invented payment sentence number {n} of the clause.\n" for n in range(80)
    )
    got = CI.find_clause([(3, long)], "9.3")
    assert got["shortened"] is True and len(got["text"]) <= CI.MAX_CLAUSE_CHARS
    assert long.startswith(
        got["text"]
    )  # verbatim lines, never a word that is not on the page


def test_the_named_parts_clause_is_listed_first_and_a_clause_of_a_named_part_is_never_looked_up_in_another(
    monkeypatch,
):
    on(monkeypatch)
    _reranker(monkeypatch, 1.0)
    _hold("con-b", {1: SCHEDULE_B, 2: CLAUSE})
    _hold(
        "con-a", {1: "SCHEDULE A\nINVENTED AGREEMENT\n", 2: CLAUSE}
    )  # holds the same number: a different clause
    got = CI.cited_first(
        ["REF.1 Schedule B, clause 4.2.1"], ["con-a", "con-b"], "q", lambda doc: []
    )
    assert [(h["document_id"], h["page_start"], h["locator"]) for h in got["hits"]] == [
        ("con-b", 2, "Schedule B, 4.2.1 Invented Lining")
    ]
    assert got["said"] == ["Schedule B clause 4.2.1: found on page 2"]
    got = CI.cited_first(
        ["REF.1 Schedule Q, clause 4.2.1"], ["con-a", "con-b"], "q", lambda doc: []
    )
    assert got["hits"] == [] and got["said"] == [
        "Schedule Q clause 4.2.1: not held among the contracts you may read"
    ]
    got = CI.cited_first(
        ["REF.1 Schedule B, clause 9.9"], ["con-a", "con-b"], "q", lambda doc: []
    )
    assert got["hits"] == [] and got["said"] == [
        "Schedule B clause 9.9: the clause was not found in that contract"
    ]


def test_a_named_part_with_no_clause_is_searched_first(monkeypatch):
    on(monkeypatch)
    _hold("con-b", {1: SCHEDULE_B})
    asked = []
    got = CI.cited_first(["REF.1 Schedule B"], ["con-b"], "q",
                         lambda doc: asked.append(doc) or [{"document_id": doc, "page_start": 1, "page_end": 1, "text": "Invented hit."}])  # fmt: skip
    assert (
        asked == ["con-b"]
        and got["hits"][0]["cited"]
        and got["said"] == ["Schedule B: searched first (1 passage)"]
    )


# ---- 5 a clause with no part: every part (C)


def test_every_part_is_looked_up_and_the_parts_without_it_are_counted(monkeypatch):
    on(monkeypatch)
    _reranker(monkeypatch, 1.5)
    for doc, text in (
        ("con-a", CLAUSE),
        ("con-b", OTHER),
        ("con-c", "Invented preface\n" + CLAUSE),
    ):
        _hold(doc, {2: text})
    hits, c = CI.in_every_part(
        "4.2.1",
        ["con-a", "con-b", "con-c"],
        "What lining applies?",
        {"invented", "lining"},
    )
    assert [
        (h["document_id"], h["page_start"], h["locator"], h["cited"]) for h in hits
    ] == [
        ("con-a", 2, "4.2.1 Invented Lining", "4.2.1"),
        ("con-c", 2, "4.2.1 Invented Lining", "4.2.1"),
    ]
    assert all(
        h["rerank_score"] == 1.5 for h in hits
    )  # the reranker's own score of each passage
    assert c == {
        "clause": "4.2.1",
        "found_in": 2,
        "of": 3,
        "failed": 0,
        "shortened": 0,
        "not_listed": 0,
        "other_title": 0,
    }
    assert (
        CI._every_part_line(c)
        == "clause 4.2.1 (no part named): found under its title in 2 of 3 contract parts"
    )


def test_without_a_reranker_the_passages_stay_unscored_never_invented(monkeypatch):
    on(monkeypatch)
    _reranker(monkeypatch)
    _hold("con-a", {1: CLAUSE})
    hits, _c = CI.in_every_part(
        "4.2.1", ["con-a"], "What lining applies?", {"invented", "lining"}
    )
    assert hits[0]["rerank_score"] is None


def test_an_unnamed_clause_in_many_parts_lists_the_best_fits_and_counts_the_rest(
    monkeypatch,
):
    on(monkeypatch)
    docs = [f"con-{n}" for n in range(6)]
    for n, doc in enumerate(docs):
        _hold(doc, {2: CLAUSE.replace("two coats", f"{n} invented coats")})
    monkeypatch.setattr(
        "app.reranker.rerank",
        lambda q, passages, batch=None: [
            (i, float(t.count("3 invented") * 5 + t.count("1 invented") * 4))
            for i, t in passages
        ],
    )
    hits, c = CI.in_every_part("4.2.1", docs, "q", {"invented", "lining"})
    assert [h["document_id"] for h in hits][:2] == ["con-3", "con-1"] and len(
        hits
    ) == CI.CITED_PARTS_LISTED
    assert c["found_in"] == 6 and c["not_listed"] == 3
    assert (
        "the 3 that best fit the question listed, 3 more not listed"
        in CI._every_part_line(c)
    )


# ---- the search and its caller (A and C)


def test_the_search_lists_what_the_form_cites_first_and_once_and_no_form_is_as_before(
    monkeypatch,
):
    on(monkeypatch)
    _reranker(monkeypatch, 0.5)
    for doc in ("con-a", "con-b"):
        _hold(doc, {2: CLAUSE})

    def fake(
        question, **kw
    ):  # the meaning search found the same page of con-a, and another page
        return {"hits": [{"document_id": kw["document_id"], "page_start": p, "page_end": p, "text": f"invented {p}", "rerank_score": 3.0 - p} for p in (2, 5)]}  # fmt: skip

    monkeypatch.setattr("app.search.search", fake)
    got = C.search_all(
        "Please confirm the invented lining.",
        frozenset({"con-a", "con-b"}),
        cited_from=["REF.1 Invented study, clause 4.2.1 Invented Lining"],
    )
    assert [
        (h["document_id"], h["page_start"], bool(h.get("cited")))
        for h in got["hits"][:2]
    ] == [("con-a", 2, True), ("con-b", 2, True)]
    assert not [
        h for h in got["hits"][2:] if h["page_start"] == 2
    ]  # the same page is not listed twice
    assert got["coverage"]["line"].endswith(
        "Looked up first, as the form cites them: clause 4.2.1 (no part named): found under its title in 2 of 2 contract parts."
    )
    plain = C.search_all(
        "Please confirm clause 4.2.1 for the invented lining.",
        frozenset({"con-a", "con-b"}),
    )  # no form
    assert (
        not [h for h in plain["hits"] if h.get("cited")]
        and plain["coverage"]["cited_first"] == []
    )
    assert plain["coverage"]["line"] == C.coverage_line(2, 2, 2) + C.standards_line(
        0, 0, False
    )  # no held standard here: said


def test_a_cited_passage_is_never_held_back_and_the_cut_counts_searched_passages_only():
    cited = [
        {"document_id": f"c{n}", "cited": "4.2.1", "rerank_score": -9.0}
        for n in range(3)
    ]
    searched = [
        {"document_id": f"s{n}", "rerank_score": 5.0 - n * 0.1} for n in range(20)
    ]
    hits = cited + searched
    assert not any(C.held_back(hits, n, h) for n, h in enumerate(cited))
    kept = [h for n, h in enumerate(hits) if not C.held_back(hits, n, h)]
    assert len(kept) == len(cited) + C.LISTED
    assert C.floor_note(hits, len(kept)) == C.floor_note(searched, C.LISTED)


def test_the_evidence_row_is_located_at_the_cited_clause_and_the_caller_passes_the_forms_texts(
    monkeypatch,
):
    from app.technical_queries import import_message, prepare_evidence

    from .test_technical_queries import envelope

    on(monkeypatch)
    _reranker(monkeypatch, 2.0)
    for doc in ("k1", "k2"):
        _hold(doc, {4: "Invented preface line.\n" + CLAUSE + OTHER})
    monkeypatch.setattr("app.search.search", lambda q, **k: {"hits": []})
    passed = []
    real = C.search_all

    def as_if_the_form_cited(
        cut, allowed, progress, form_texts
    ):  # the caller hands the form pages' texts (none attached here)
        passed.append(form_texts)
        return real(
            cut,
            allowed,
            progress,
            ["REF.1 Invented study, clause 4.2.1 Invented Lining"],
        )

    monkeypatch.setattr(C, "search_all", as_if_the_form_cited)
    mail = envelope("cited-1")
    mail["question"] = mail["body"] = "Please confirm the invented lining."
    item, _ = import_message(mail, "u1", False, False)
    got = prepare_evidence(item["id"], frozenset({"k1", "k2"}), "u1", True, False, "u1")
    assert passed == [
        []
    ]  # the form's texts are passed (this query has no attached form)
    rows = [(e["document_id"], e["page_start"], e["locator"]) for e in got["evidence"]]
    assert sorted(rows) == [
        ("k1", 4, "4.2.1 Invented Lining"),
        ("k2", 4, "4.2.1 Invented Lining"),
    ]
    assert all(
        e["exact_quote"].startswith("4.2.1 Invented Lining") for e in got["evidence"]
    )


def test_a_partless_clause_is_listed_only_under_its_own_title_and_never_without_one(
    monkeypatch,
):
    """Measured on the stored forms (26 Nov 2026): a part-less "Section 13" or "Section 7.2" on a reference line named a section of a
    non-contract document; the contracts' clauses of that number were OTHER clauses. They are counted apart, never listed."""
    on(monkeypatch)
    _reranker(monkeypatch, 1.0)
    _hold("con-a", {2: CLAUSE})  # 4.2.1 Invented Lining
    _hold(
        "con-b",
        {
            2: "4.2.1 Invented Payment Terms\nThe invented invoice is monthly.\nAnother invented line.\n"
        },
    )
    got = CI.cited_first(
        ["REF.1 Invented design basis, Section 4.2.1 Invented Lining"],
        ["con-a", "con-b"],
        "q",
        lambda doc: [],
    )
    assert [h["document_id"] for h in got["hits"]] == ["con-a"]
    assert got["said"] == [
        "clause 4.2.1 (no part named): found under its title in 1 of 2 contract parts; 1 hold a clause of that number with another title (not listed)"
    ]
    got = CI.cited_first(
        ["REF.1 Invented design basis, Section 4.2.1"],
        ["con-a", "con-b"],
        "q",
        lambda doc: [],
    )
    assert got["hits"] == [] and got["said"] == [
        "clause 4.2.1 (no part named, no title): not looked up; it names no contract part"
    ]


# ---- the owner's scope (26 Nov 2026): held standards are searched too, and every passage says its source


def _hold_standard(doc, number, role, pages):
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,?,?)",
            (
                doc,
                f"{number}.pdf",
                doc.encode().hex().ljust(64, "0")[:64],
                1,
                f"{number}.pdf",
                "ready",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO document_classification(document_id,document_role,document_number,suggested_by) VALUES (?,?,?,?)",
            (doc, role, number, "rules"),
        )
    for n, text in pages.items():
        _page(doc, n, text)


COATING = "6.1 Invented Coating\nThe invented coating shall be 250 invented microns.\nIt shall be applied in two invented coats.\n"


def test_the_held_standards_are_the_rule_books_the_caller_may_read_never_a_contract(
    monkeypatch,
):
    on(monkeypatch)
    _hold("con-a", {2: CLAUSE})
    _hold_standard("std-co", "ZQ-STD-001", "COMPANY_STANDARD", {1: COATING})
    _hold_standard("std-pub", "API 9999", None, {1: COATING})
    got = {
        e["id"] for e in C.standard_entries(frozenset({"con-a", "std-co", "std-pub"}))
    }
    assert got == {"std-co", "std-pub"}
    assert (
        C.standard_entries(frozenset({"con-a"})) == []
        and C.standard_entries(frozenset({"std-pub"}))[0]["id"] == "std-pub"
    )


def test_the_standards_are_searched_together_beside_each_contract_and_the_line_says_so(
    monkeypatch,
):
    on(monkeypatch)
    _hold("con-a", {2: CLAUSE})
    _hold_standard("std-co", "ZQ-STD-001", "COMPANY_STANDARD", {1: COATING})
    calls = []

    def fake(question, **kw):
        calls.append(kw.get("document_id") or sorted(kw["allowed_document_ids"]))
        doc = kw.get("document_id") or "std-co"
        return {
            "hits": [
                {
                    "document_id": doc,
                    "page_start": 1,
                    "page_end": 1,
                    "text": f"invented {doc}",
                    "rerank_score": 1.0,
                }
            ]
        }

    monkeypatch.setattr("app.search.search", fake)
    got = C.search_all("What coating applies?", frozenset({"con-a", "std-co"}))
    assert calls == [
        "con-a",
        ["std-co"],
    ]  # each contract on its own, the standards together
    assert {h["document_id"] for h in got["hits"]} == {"con-a", "std-co"}
    assert (
        got["coverage"]["line"]
        == "Searched 1 of 1 contracts, hits in 1. Searched the 1 held standards you may read together, hits in 1."
    )


def test_a_standard_the_form_cites_is_looked_up_first_by_its_clause(monkeypatch):
    on(monkeypatch)
    _reranker(monkeypatch, 1.0)
    _hold_standard("std-pub", "API 9999", None, {3: "Invented preface.\n" + COATING})
    standards = C.standard_entries(frozenset({"std-pub"}))
    got = CI.cited_first(
        ["REF.1 API 9999 section 6.1 Invented Coating"],
        [],
        "q",
        lambda doc: [],
        standards,
    )
    assert [(h["document_id"], h["page_start"], h["locator"]) for h in got["hits"]] == [
        ("std-pub", 3, "API 9999, 6.1 Invented Coating")
    ]
    assert got["said"] == ["API 9999 clause 6.1: found on page 3"]
    got = CI.cited_first(
        ["REF.1 API 8888 section 6.1"], [], "q", lambda doc: [], standards
    )
    assert got["hits"] == [] and got["said"] == [
        "API 8888 clause 6.1: not held among the standards you may read"
    ]


def test_every_evidence_row_says_its_source_kind_and_name(monkeypatch):
    on(monkeypatch)
    _hold("con-a", {2: CLAUSE}, "invented-contract.pdf")
    _hold_standard("std-co", "ZQ-STD-001", "COMPANY_STANDARD", {1: COATING})
    _hold_standard("std-pub", "API 9999", None, {1: COATING})
    with db.connect() as conn:
        assert C.source_of(conn, "con-a")[0] == C.SOURCE_CONTRACT
        assert C.source_of(conn, "std-co") == (C.SOURCE_COMPANY, "ZQ-STD-001")
        assert C.source_of(conn, "std-pub") == (C.SOURCE_STANDARD, "API 9999")
        assert C.source_of(conn, "doc-unknown") == (C.SOURCE_OTHER, "")


# ---- builder C's review notes (26 Nov 2026)


def test_a_scanned_page_one_is_read_from_its_recognised_text_for_the_parts_heading(
    monkeypatch,
):
    """A scanned page 1 whose text layer is junk hides the heading unless the page is read as every other page is (needs_ocr)."""
    on(monkeypatch)
    hold_contract("con-scan")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES ('con-scan',1,'~~ junk ~~',10,1,1)"
        )
        conn.execute(
            "INSERT INTO page_ocr(document_id,page_no,text,char_count,engine,model,dpi,box_count,seconds,recognised_at,batch_no)"
            " VALUES ('con-scan',1,?,?,'invented','invented',300,1,0,'2026-01-01T00:00:00Z',1)",
            (SCHEDULE_B, len(SCHEDULE_B)),
        )
    assert CI.which(["con-scan"], (("schedule", "B"), None)) == ["con-scan"]


def test_one_unreadable_cited_document_is_said_and_the_forms_other_citations_go_on(
    monkeypatch,
):
    on(monkeypatch)
    _reranker(monkeypatch, 1.0)
    _hold("con-b", {1: SCHEDULE_B, 2: CLAUSE})
    _hold("con-c", {1: "SCHEDULE C\nINVENTED\n", 2: CLAUSE})
    real = CI._part_pages

    def pages(conn, doc):
        if doc == "con-b":
            raise RuntimeError("invented read error")
        return real(conn, doc)

    monkeypatch.setattr(CI, "_part_pages", pages)
    got = CI.cited_first(
        ["REF.1 Schedule B, clause 4.2.1", "REF.2 Schedule C, clause 4.2.1"],
        ["con-b", "con-c"],
        "q",
        lambda d: [],
    )
    assert got["said"] == [
        "Schedule B clause 4.2.1: that document could not be read",
        "Schedule C clause 4.2.1: found on page 2",
    ]
    assert [h["document_id"] for h in got["hits"]] == ["con-c"]
