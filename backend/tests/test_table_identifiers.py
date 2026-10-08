"""Identifiers with or without a prefix, and front matter on the Claude lane.

1. "According to <standard>, what is the maximum carbon content for alloy
   UNS N06625?" was refused - "UNS N06625 does not appear anywhere in the
   indexed documents" - while the standard's material tables list the alloy.
   The table text WAS indexed (checked read-only on the live database: every
   searchable chunk holding the code is in the index, six of them tables).
   The gate was too strict: the standard's tables print the bare code
   "N06625" under their UNS column, and only the whole phrase "UNS N06625"
   was ever looked for. An identifier now matches with or without an optional
   prefix (`reference/identifier_prefixes.json`) when what remains is still a
   code - never a bare number.

2. #610 follow-up: with Claude answering, a point quoted from a foreword or
   revision history was counted as "found on the page". It is now counted in
   the total, never as found - the rule the quoted answer already follows.

Invented documents only. Mutations M3501-M3511.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import answer as answer_mod
from app import chat_claude_first as ccf
from app import db, keyword
from app import search as search_mod
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

# ------------------------------------------------- 1. prefixes, end to end

ALLOYS = [
    ["STD-N-013 Sour Service Alloy Selection, Revision 0",
     "1 Scope",
     "1.1 This standard limits the composition of corrosion resistant alloys for sour service.",
     "2 Composition",
     "2.1 Nickel alloys shall meet the composition limits in Table 1."],
    ["Table 1 Composition limits of nickel alloys",
     "UNS  C max  Cr  Ni min",
     "N06625  0.08  20.0-23.0  58.0",
     "N08825  0.04  19.5-23.5  38.0",
     "N10276  0.01  14.5-16.5  51.0"],
]

PREFIXED = "What is the maximum carbon content for alloy UNS N06625?"
NAMED = "According to STD-N-013, what is the maximum carbon content for alloy UNS N06625?"


@pytest.fixture
def alloys(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "STD-N-013.pdf"
    doc = pymupdf.open()
    for lines in ALLOYS:
        page = doc.new_page()
        for i, line in enumerate(lines):
            page.insert_text((72, 100 + i * 18), line, fontsize=11)
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        doc_id = TestClient(app).post(
            "/api/documents", files={"file": ("STD-N-013.pdf", fh, "application/pdf")}
        ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    yield frozenset({doc_id})
    db.reset_connection()


def test_the_table_is_a_searchable_table_chunk(alloys):
    """The fixture is what it claims: the rows are a TABLE chunk on page 2,
    and the bare code finds it. If this fails the tests below prove nothing."""
    rows = db.connect().execute(
        "SELECT kind, page_start FROM chunks WHERE text LIKE '%N06625%'").fetchall()
    assert [(r["kind"], r["page_start"]) for r in rows] == [("table", 2)]
    assert keyword.search("N06625", allowed_document_ids=alloys)


@pytest.mark.parametrize("question", [PREFIXED, NAMED])
def test_a_prefixed_identifier_finds_the_table_that_prints_the_bare_code(alloys, question):
    """THE DEFECT: refused with "UNS N06625 does not appear ..."."""
    r = answer_mod.answer(question, allowed_document_ids=alloys)
    assert r["answer_type"] == "extract", r.get("reason")
    quoted = r["passage"]
    assert quoted["kind"] == "table"
    assert "N06625  0.08" in quoted["text"]
    # citable: the cited span covers the page the row is on
    assert quoted["page_start"] <= 2 <= quoted["page_end"]


def test_the_gate_counts_the_table_row_as_covering_the_identifier(alloys):
    """The gate's own reading of the passage: the row prints "N06625", and
    that covers "UNS N06625" - not merely "some other term matched"."""
    from app import lexical

    table = db.connect().execute(
        "SELECT text FROM chunks WHERE kind = 'table'").fetchone()["text"]
    verdict = lexical.assess(PREFIXED, table, allowed_document_ids=alloys)
    assert "UNS N06625" in verdict["covered"]


def test_the_keyword_search_asks_for_the_bare_code(alloys):
    table = db.connect().execute(
        "SELECT id FROM chunks WHERE kind = 'table'").fetchone()["id"]
    hits = keyword.search(PREFIXED, allowed_document_ids=alloys)
    assert table in {h["chunk_id"] for h in hits}


def test_a_code_no_document_holds_still_refuses(alloys):
    r = answer_mod.answer("What is the maximum carbon content for alloy UNS N09999?",
                          allowed_document_ids=alloys)
    assert r["answer_type"] == "insufficient_evidence"
    assert "UNS N09999" in r["reason"]


# ------------------------------------------------- 1. prefixes, the rule

@pytest.mark.parametrize(("identifier", "expected"), [
    ("UNS N06625", ["N06625"]),
    ("UNS-S31603", ["S31603"]),
    ("ASTM A216", ["A216"]),
    ("NACE MR0175", ["MR0175"]),
    ("API 610", []),        # API is not an optional prefix
    ("EN 10204", []),       # not in the list
    ("UNS 06625", []),      # what remains is a bare number, never asked for alone
])
def test_what_an_optional_prefix_drops(identifier, expected):
    assert keyword.unprefixed_forms(identifier) == expected


def test_the_bare_code_is_one_of_the_identifiers_forms():
    assert "N06625" in keyword.identifier_forms("UNS N06625")
    assert "610" not in keyword.identifier_forms("API 610")


def test_the_prefixes_come_from_the_editable_file(tmp_path, monkeypatch):
    """Generic: a prefix is data, not code. And even a listed prefix never
    leaves a bare number behind."""
    assert keyword.unprefixed_forms("XYZ Q1234") == []
    data = json.loads(keyword.PREFIX_PATH.read_text(encoding="utf-8"))
    data["prefixes"] += ["XYZ", "API"]
    edited = tmp_path / "identifier_prefixes.json"
    edited.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(keyword, "PREFIX_PATH", edited)
    keyword.reload_prefixes()
    try:
        assert keyword.unprefixed_forms("XYZ Q1234") == ["Q1234"]
        assert keyword.unprefixed_forms("API 610") == []
    finally:
        monkeypatch.undo()
        keyword.reload_prefixes()


def test_a_passage_with_the_bare_code_names_the_prefixed_identifier():
    """Ranking: the boost and the "names every identifier the reader asked
    for" guarantee both read the bare code."""
    c = search_mod.Candidate(chunk_id="t", document_id="d", filename="s.pdf", section=None,
                             page_start=2, page_end=2, text="N06625  0.08  20.0-23.0  58.0",
                             rrf=0.03)
    other = search_mod.Candidate(chunk_id="o", document_id="d", filename="s.pdf", section=None,
                                 page_start=1, page_end=1, text="Nickel alloys in sour service.",
                                 rrf=0.03)
    search_mod.apply_identifier_boost(PREFIXED, [c, other])
    assert c.names_identifiers is True
    assert c.identifier_hits == ["uns n06625"]
    assert other.names_identifiers is False


# ------------------------------------------------- 2. front matter, Claude lane

HISTORY = {"chunk_id": "h", "document_id": "d1", "filename": "d1.pdf", "page_start": 1,
           "page_end": 1, "section": "Revision history",
           "text": "Revision 2 changed the bolting material requirements for pipe supports."}
CLAUSE = {"chunk_id": "c", "document_id": "d1", "filename": "d1.pdf", "page_start": 2,
          "page_end": 2, "section": "4.1",
          "text": "Bolting material for pipe supports shall be alloy steel stud bolts."}
BOLTING = "What bolting material is required for pipe supports?"
TWO_POINTS = ('Supports use alloy steel stud bolts [S1 "shall be alloy steel stud bolts"]. '
              'The requirement was changed [S2 "changed the bolting material requirements"].')


def test_a_point_quoted_from_front_matter_is_not_a_point_found():
    """THE DEFECT: both points counted as found, one of them on a revision
    history that answers nothing."""
    text, v, claims, removed = answer_mod.verify_claims(
        TWO_POINTS, [CLAUSE, HISTORY], question=BOLTING)
    assert (v["verified"], v["total"]) == (1, 2)
    assert "[S2]" in text                       # kept and shown, never hidden
    assert [c["n"] for c in claims] == [1]      # no highlight on the foreword
    assert v["front_matter"] == 1
    assert removed == 0                         # shown, so not "removed"


def test_an_answer_quoting_only_front_matter_says_so(monkeypatch, empty_db):
    """The Claude lane refuses when no point is found; the reason must not
    claim the quotes were missing from the page - they were there."""
    _serve(monkeypatch, 'It was changed [S2 "changed the bolting material requirements"].')
    r = answer_mod.answer(BOLTING, tier="generated", allowed_document_ids=frozenset({"d1"}))
    assert r["answer_type"] == "insufficient_evidence"
    assert r["reason"] == answer_mod.FRONT_MATTER_POINTS_REASON


def test_a_question_about_the_history_counts_the_history():
    _, v, _, _ = answer_mod.verify_claims(
        TWO_POINTS, [CLAUSE, HISTORY], question="What did Revision 2 change?")
    assert (v["verified"], v["total"]) == (2, 2)


@pytest.fixture
def empty_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "e.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    yield
    db.reset_connection()


def _serve(monkeypatch, response: str) -> None:
    from app import lexical, passages as passages_mod

    monkeypatch.setattr(search_mod, "search", lambda *a, **k: {
        "hits": [dict(CLAUSE, score=5.0, rerank_score=5.0, separation=0.0, rrf=0.03, context=None),
                 dict(HISTORY, score=4.0, rerank_score=4.0, separation=0.1, rrf=0.03, context=None)],
        "mode": "hybrid", "reranked": True, "timings": {}, "total": 2, "seconds": 0.0})
    monkeypatch.setattr(lexical, "assess", lambda *a, **k: {
        "ok": True, "reason": None, "coverage": 1.0, "terms": [], "covered": [],
        "absent_from_corpus": []})
    monkeypatch.setattr(passages_mod, "expand_passage", lambda *a, **k: {})
    monkeypatch.setattr(answer_mod, "_coverage", lambda *a, **k: None)
    monkeypatch.setattr(answer_mod, "claude_lane", lambda: True)
    monkeypatch.setattr(answer_mod, "_call_model", lambda prompt, timeout=180.0: {
        "response": response})


def test_the_generated_answer_counts_front_matter_as_not_found(monkeypatch, empty_db):
    """Through the Claude lane of `answer()`: the question reaches the count."""
    _serve(monkeypatch, TWO_POINTS)
    r = answer_mod.answer(BOLTING, tier="generated", allowed_document_ids=frozenset({"d1"}))
    assert r["answer_type"] == "generated", r.get("reason")
    assert (r["verification"]["verified"], r["verification"]["total"]) == (1, 2)


def test_the_claude_first_answer_counts_front_matter_as_not_found():
    response = SimpleNamespace(text=TWO_POINTS, provider="claude", model_tag="claude-test",
                               cost_usd=0.0, truncated=False)
    body = ccf._finish(response, [CLAUSE, HISTORY], [], 0.0, None, question=BOLTING)
    assert (body["verification"]["verified"], body["verification"]["total"]) == (1, 2)
