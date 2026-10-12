"""#513 (R29 #833): OKF v1 - one cited concept file per standard, clause,
requirement and equipment type, built from stored facts only.

The rule of the format: NO LINK WITHOUT A RESOLVING CITATION. A concept whose
source does not resolve is still written, with a named state and no links,
and is counted - never dropped silently, never linked on trust.

Invented standard only; no model, no socket.
"""
from __future__ import annotations

import pytest

from app import db, okf, standards, submittal_review
from app.config import settings

NOW = "2026-10-12T00:00:00Z"
NOISE = "The noise level shall not exceed 90 dB(A)."
VIBRATION = "The vibration velocity shall not exceed 3 mm/s."


@pytest.fixture(autouse=True)
def library(tmp_path, monkeypatch):
    """One invented standard: two chunks on two pages, two requirements in
    two clauses, one of them for an equipment type."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "okf.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    with db.connect() as conn:
        for doc in ("doc_std", "doc_other"):
            conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
                         "uploaded_at) VALUES (?,?,?,1,'x','ready',2,?)", (doc, f"{doc}.pdf", f"sha-{doc}", NOW))
        for chunk, doc, page, text in (("c1", "doc_std", 1, NOISE), ("c2", "doc_std", 2, VIBRATION),
                                       ("cx", "doc_other", 1, "Another document says something else.")):
            conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,"
                         "text,token_count,content_hash,retrievable) VALUES (?,?,?,1,?,?,NULL,'prose',?,1,?,1)",
                         (chunk, doc, f"{doc}.pdf", page, page, text, f"h-{chunk}"))
    standards.create_requirement(standard_document_id="doc_std", chunk_id="c1", clause="5.3.3", page=1,
                                 requirement_text=NOISE, source_text=NOISE,
                                 structured={"requirement_type": "numeric_limit"})
    standards.create_requirement(standard_document_id="doc_std", chunk_id="c2", clause="6.1", page=2,
                                 requirement_text=VIBRATION, source_text=VIBRATION,
                                 structured={"requirement_type": "numeric_limit"})
    with db.connect() as conn:      # the extraction's own column; `create_requirement` does not take it
        conn.execute("UPDATE standard_requirements SET equipment_type = 'Centrifugal pump' WHERE clause = '5.3.3'")
    yield
    db.reset_connection()


ALL = frozenset({"doc_std", "doc_other"})


def _build(ids=("doc_std",), allowed=ALL):
    return okf.build(ids, allowed_document_ids=allowed)


def _by_kind(built) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {kind: [] for kind in okf.KINDS}
    for concept in built["concepts"]:
        out[concept["kind"]].append(concept)
    return out


def test_one_concept_per_standard_clause_requirement_and_equipment_type():
    built = _build()
    kinds = _by_kind(built)
    assert {k: len(v) for k, v in kinds.items()} == {"standard": 1, "clause": 2, "requirement": 2, "equipment_type": 1}
    assert built["report"]["concepts"] == {"standard": 1, "clause": 2, "requirement": 2, "equipment_type": 1}
    assert built["report"]["links"] == {"part_of": 2, "in_clause": 2, "applies_to": 1}
    assert built["report"]["unresolved"] == {} and all(c["state"] == okf.OK for c in built["concepts"])
    assert kinds["equipment_type"][0]["title"] == "Centrifugal pump"
    assert sorted(c["facts"]["clause"] for c in kinds["clause"]) == ["5.3.3", "6.1"]


def test_every_link_has_a_citation_that_resolves_and_a_target_in_the_set():
    """THE ACCEPTANCE CRITERION of #513."""
    built = _build()
    assert okf.problems(built["concepts"]) == []
    links = [(c["id"], link) for c in built["concepts"] for link in c["links"]]
    assert len(links) == 5
    for _owner, link in links:
        assert okf.resolve(link["cite"]) is None
        assert link["cite"]["document_id"] == "doc_std" and link["cite"]["chunk_id"] in ("c1", "c2")


@pytest.mark.parametrize("citation, why", [
    ({"document_id": "doc_std", "page": 1, "chunk_id": "c1", "quote": NOISE}, None),
    ({"document_id": "doc_std", "page": 1, "chunk_id": "c1", "quote": "the  NOISE level shall\nnot exceed 90 dB(A)."}, None),
    ({"document_id": "doc_std", "page": 1, "chunk_id": None}, okf.NO_CHUNK),
    ({"document_id": "doc_std", "page": 1, "chunk_id": "gone"}, okf.CHUNK_MISSING),
    ({"document_id": "doc_std", "page": 1, "chunk_id": "cx"}, okf.WRONG_DOCUMENT),      # opens something real and wrong
    ({"document_id": "doc_std", "page": 2, "chunk_id": "c1"}, okf.PAGE_OUTSIDE),
    ({"document_id": "doc_std", "page": 1, "chunk_id": "c1", "quote": "shall not exceed 95 dB(A)"}, okf.QUOTE_ABSENT),
    (None, okf.NO_CHUNK),
])
def test_what_resolving_means(citation, why):
    assert okf.resolve(citation) == why


def test_a_requirement_whose_words_are_not_in_its_chunk_is_named_and_carries_no_link():
    """Never dropped silently, never linked on trust."""
    with db.connect() as conn:
        conn.execute("UPDATE chunks SET text = 'The page was re-read and says something else.' WHERE id = 'c2'")
    built = _build()
    [unresolved] = [c for c in built["concepts"] if c["state"] == okf.CITATION_UNRESOLVED]
    assert unresolved["kind"] == "requirement" and unresolved["unresolved"] == okf.QUOTE_ABSENT
    assert unresolved["links"] == [] and unresolved["body"] == VIBRATION
    assert built["report"]["unresolved"] == {okf.QUOTE_ABSENT: 1}
    assert built["report"]["concepts"]["clause"] == 1          # its clause is not made from an unresolved source
    assert okf.problems(built["concepts"]) == []


def test_a_broken_set_is_reported_link_by_link():
    built = _build()
    concepts = built["concepts"]
    requirement = next(c for c in concepts if c["kind"] == "requirement")
    requirement["links"][0]["cite"] = {"document_id": "doc_std", "page": 1, "chunk_id": "cx"}
    requirement["links"].append({"rel": "in_clause", "to": "okf:clause:nowhere", "cite": dict(requirement["source"])})
    found = okf.problems(concepts)
    assert len(found) == 2 and any(okf.WRONG_DOCUMENT in line for line in found)
    assert any("not in the set" in line for line in found)


def test_only_what_the_caller_may_read_and_the_library_holds():
    built = okf.build(["doc_std", "doc_other", "doc_absent"], allowed_document_ids=frozenset({"doc_other"}))
    assert built["report"]["not_readable"] == ["doc_std", "doc_absent"]
    assert [c["id"] for c in built["concepts"]] == [okf.concept_id("standard", "doc_other")]
    held = okf.build(["doc_absent"], allowed_document_ids=frozenset({"doc_absent"}))
    assert held["report"]["not_held"] == ["doc_absent"] and held["concepts"] == []


def test_a_superseded_requirement_is_not_in_the_map():
    with db.connect() as conn:
        conn.execute("UPDATE standard_requirements SET superseded_at = ? WHERE clause = '6.1'", (NOW,))
    assert _build()["report"]["concepts"]["requirement"] == 1


def test_a_file_reads_back_as_the_concept_it_was_written_from():
    for concept in _build()["concepts"]:
        text = okf.render(concept)
        assert text.startswith("---\n") and okf.parse(text) == concept
    requirement = next(c for c in _build()["concepts"] if c["kind"] == "requirement")
    assert okf.render(requirement).rstrip().endswith(requirement["body"])


@pytest.mark.parametrize("text", ["", "no frontmatter here", "---\nkind: \"clause\"\n", "---\nnot a pair\n---\n"])
def test_a_file_that_is_not_okf_is_an_error_not_an_empty_concept(text):
    with pytest.raises(ValueError):
        okf.parse(text)


def test_the_same_stored_facts_give_the_same_ids_and_hashes():
    first, second = _build(), _build()
    assert [(c["id"], c["content_sha256"]) for c in first["concepts"]] == \
        [(c["id"], c["content_sha256"]) for c in second["concepts"]]
    with db.connect() as conn:
        conn.execute("UPDATE standard_requirements SET source_text = ? WHERE clause = '6.1'",
                     ("The vibration velocity shall not exceed 3 mm/s.",))
    assert _build()["concepts"] == first["concepts"]


def test_files_are_written_under_the_local_data_folder_and_nowhere_else(tmp_path):
    built = _build()
    counts = okf.write(built["concepts"])
    assert counts == {"written": 6, "kinds": {"standard": 1, "clause": 2, "requirement": 2, "equipment_type": 1}}
    files = sorted(p.relative_to(okf.root()).as_posix() for p in okf.root().rglob("*.md"))
    assert len(files) == 6 and files[0].startswith("clause/") and okf.root().is_relative_to(tmp_path)
    for concept in built["concepts"]:
        assert okf.parse((okf.root() / okf.file_name(concept)).read_text(encoding="utf-8")) == concept
    with pytest.raises(ValueError, match="local data folder"):
        okf.write(built["concepts"], out_dir=tmp_path.parent / "elsewhere")


def test_a_set_that_breaks_the_rule_is_not_written():
    built = _build()
    next(c for c in built["concepts"] if c["links"])["links"][0]["cite"]["chunk_id"] = "gone"
    with pytest.raises(ValueError, match="nothing was written"):
        okf.write(built["concepts"])
    assert not okf.root().exists()


def test_the_report_holds_counts_and_ids_only():
    report = _build()["report"]
    text = str(report)
    assert "noise" not in text.lower() and "vibration" not in text.lower() and "Centrifugal" not in text


# ------------------------------------------------------- readings from a table

def _table_value(row_label: str, value: str, chunk: str = "c2"):
    """A requirement the extractor read from a table: its stored sentence is
    COMPOSED from a row label, a column and a cell, not quoted from the page."""
    made = standards.create_requirement(
        standard_document_id="doc_std", chunk_id=chunk, clause=None, page=2,
        requirement_text=f"{row_label}: velocity limit is {value}", source_text=f"{row_label} | limit | {value}",
        structured={"requirement_type": "table_value"})
    with db.connect() as conn:
        conn.execute("UPDATE standard_requirements SET table_row = ?, raw_value = ? WHERE id = ?",
                     (row_label, value, made["id"]))
    return made["id"]


def test_a_table_reading_resolves_by_its_row_label_and_its_value_not_by_its_composed_sentence():
    """Measured on the real library (12 Oct 2026): every table value failed
    the quote check, because its stored sentence is composed and stands
    nowhere on the page. The proof for a table reading is that its row label
    and its value are both in the cited chunk."""
    good = _table_value("vibration velocity", "3")
    wrong_value = _table_value("vibration velocity", "7")
    wrong_row = _table_value("shaft runout", "3")
    states = {c["facts"]["requirement_id"]: (c["state"], c.get("unresolved"))
              for c in _build()["concepts"] if c["kind"] == "requirement"}
    assert states[good] == (okf.OK, None)
    assert states[wrong_value] == (okf.CITATION_UNRESOLVED, okf.CELL_ABSENT)
    assert states[wrong_row] == (okf.CITATION_UNRESOLVED, okf.CELL_ABSENT)
    report = _build()["report"]
    assert report["unresolved"] == {okf.CELL_ABSENT: 2} and report["requirements_without_a_clause"] == 1


def test_a_table_reading_with_no_row_label_or_no_value_does_not_resolve():
    assert okf.resolve({"document_id": "doc_std", "page": 2, "chunk_id": "c2", "cells": ["", "3"]}) == okf.CELL_ABSENT
    assert okf.resolve({"document_id": "doc_std", "page": 2, "chunk_id": "c2", "cells": [None, None]}) == okf.CELL_ABSENT
    assert okf.resolve({"document_id": "doc_std", "page": 2, "chunk_id": "c2",
                        "cells": ["vibration velocity", "3"]}) is None


# ------------------------------------------------------------------ the route

def test_the_route_reports_counts_for_a_standard_the_caller_may_read(monkeypatch):
    from fastapi.testclient import TestClient

    from app import access
    from app.main import app
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    client = TestClient(app)
    body = client.get("/api/standards/doc_std/okf").json()
    assert body["concepts"] == {"standard": 1, "clause": 2, "requirement": 2, "equipment_type": 1}
    assert body["links"] == {"part_of": 2, "in_clause": 2, "applies_to": 1}
    assert body["unresolved"] == {} and body["problems"] == 0 and body["document_id"] == "doc_std"
    assert "noise" not in str(body).lower()                     # counts and ids, never a sentence
    assert client.get("/api/standards/doc_absent/okf").status_code == 404
    assert not okf.root().exists()                              # read only: no file is made
