"""Follow-up to #1920 (the 12-question test): a clause locator and a key-term match score on every evidence passage, decided by code.
Invented contract text only; no model, no network."""

from __future__ import annotations

import pytest

from app import db
from app import technical_queries as tq
from app import technical_query_match as M
from app.config import settings
from tests.test_tq_g_feature_off import attachment_query, envelope, hold_contract, on  # noqa: F401 - helpers (autouse storage comes with the import)
from tests.test_tq_g_feature_off import storage  # noqa: F401 - fixture

PAGE = """ARTICLE 6 GENERAL
6.1 Painting
Carbon steel tanks shall receive three coats of coating at 250 microns total.
12 Set pressure bar
6.2 Inspection
Inspection is by the Company."""


def test_the_locator_is_the_nearest_clause_heading_above_the_passage_and_a_table_row_is_not_a_heading():
    assert (
        M.heading_above(PAGE, "three coats of coating at 250 microns") == "6.1 Painting"
    )
    assert M.heading_above(PAGE, "Inspection is by the Company.") == "6.2 Inspection"
    assert (
        M.heading_above(PAGE, "a sentence that is not on the page") is None
    )  # never a guess
    assert (
        M._heading_of("12 Set pressure bar") is None
        and M._heading_of("A random sentence about tanks") is None
    )
    assert (
        M._heading_of("Annex A Forms") == "Annex A Forms"
        and M._heading_of("6 GENERAL CONDITIONS") == "6 GENERAL CONDITIONS"
    )


def test_a_passage_with_no_heading_on_its_page_takes_the_last_heading_of_the_page_before_or_nothing():
    no_head = "Carbon steel tanks shall receive three coats."
    assert (
        M.locator_for(no_head, PAGE, "Carbon steel tanks shall receive three coats.")
        == "6.2 Inspection"
    )
    assert (
        M.locator_for(no_head, None, "Carbon steel tanks shall receive three coats.")
        is None
    )
    assert (
        M.locator_for(
            no_head,
            "plain text with no heading at all",
            "Carbon steel tanks shall receive three coats.",
        )
        is None
    )


def test_the_searchs_own_heading_wins_when_it_names_a_clause_number():
    assert (
        M.locator_for(
            PAGE, None, "Inspection is by the Company.", "Part 2 > 9.4.1 Welding"
        )
        == "Part 2 > 9.4.1 Welding"
    )
    assert (
        M.locator_for(PAGE, None, "Inspection is by the Company.", "General")
        == "6.2 Inspection"
    )  # no number in it: the page text decides


def test_key_terms_drop_filler_and_stem_lightly():
    terms = M.key_terms(
        "Does the contract allow the contractor to change the coating thickness on carbon steel tanks?"
    )
    assert (
        "the" not in terms
        and "contract" not in terms
        and "carbon" in terms
        and "tank" in terms
        and "coat" in terms
    )
    assert (
        M.key_terms("model Q7 set pressure") == ["model", "q7", "set", "pressure"]
        and M.key_terms("") == []
    )


def test_a_passage_matches_with_half_of_the_key_terms_and_the_count_is_stated():
    terms = M.key_terms(
        "coating thickness for carbon steel tanks"
    )  # coat, thicknes, carbon, steel, tank
    good = M.score(
        terms,
        "Carbon steel tanks shall receive three coats of coating at 250 microns thickness.",
    )
    weak = M.score(terms, "The tank shall be inspected by the Company.")
    assert good["count"] == 5 and good["terms"] == 5 and good["matches"] is True
    assert weak["count"] == 1 and weak["matches"] is False
    assert (
        M.required(1) == 1
        and M.required(2) == 2
        and M.required(5) == 3
        and M.required(6) == 3
    )


def test_the_key_term_counts_are_information_only_no_verdict_is_drawn_from_them():
    terms = M.key_terms("coating thickness for carbon steel tanks")
    none = M.coverage_of(
        terms,
        [
            M.score(terms, "Insurance certificates are due annually."),
            M.score(terms, "Payment is monthly."),
        ],
    )
    assert none == {
        "key_terms": 5,
        "passages": 2,
        "matching_passages": 0,
    }  # counts only: nothing says "not covered"
    assert "not covered" not in repr(none).casefold() and not hasattr(
        M, "NOT_COVERED_LINE"
    )


def _query_with_contract(monkeypatch, body, page_text):
    on(monkeypatch)
    monkeypatch.setattr("app.technical_query_questions._ask", lambda text: [])
    item, _ = tq.import_message(
        {**envelope("m1"), "body": body, "question": body}, "u1", False, False
    )
    hold_contract("con-a")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES ('con-a',4,?,?,0,1)",
            (page_text, len(page_text)),
        )
    return item


def test_prepare_evidence_stores_the_locator_and_the_match_and_shows_it_in_the_card_and_the_word_file(
    monkeypatch, tmp_path
):
    from zipfile import ZipFile

    from app.technical_query_docx import render

    item = _query_with_contract(
        monkeypatch, "What coating thickness applies to carbon steel tanks?", PAGE
    )
    quote = (
        "Carbon steel tanks shall receive three coats of coating at 250 microns total."
    )
    monkeypatch.setattr(
        "app.search.search",
        lambda q, **k: {
            "hits": [
                {
                    "document_id": "con-a",
                    "page_start": 4,
                    "page_end": 4,
                    "text": quote,
                    "score": 1.0,
                }
            ]
        },
    )
    got = tq.prepare_evidence(item["id"], frozenset({"con-a"}), "u1", True, False, "u1")
    (row,) = got["evidence"]
    assert (
        row["locator"] == "6.1 Painting" and row["page_start"] == 4
    )  # "clause 6.1, page 4"
    assert (row["match_count"], row["match_terms"], row["match_ok"]) == (
        4,
        5,
        1,
    )  # all but 'thickness': the passage says coats and microns
    assert (
        got["evidence_coverage"]["matching_passages"] == 1
        and "likely_not_covered" not in got["evidence_coverage"]
    )
    tq.update_evidence(
        item["id"],
        row["id"],
        "verified",
        "current",
        None,
        "u1",
        "u1",
        True,
        False,
        reviewer=True,
    )
    tq.add_draft(item["id"], "Three coats [S1].", [], [], "u1", "u1", True, False,
                 citations=[{"evidence_id": row["id"], "label": "S1", "document_id": "con-a", "page": 4, "exact_quote": quote}])  # fmt: skip
    word = (
        ZipFile(render(tq.get(item["id"], "u1", True, False), tmp_path / "r.docx"))
        .read("word/document.xml")
        .decode()
    )
    assert "6.1 Painting" in word and "4 of 5 key terms" in word


def test_a_question_no_passage_holds_the_key_terms_of_is_never_called_not_covered_and_the_top_reranker_score_is_shown(
    monkeypatch, tmp_path
):
    from zipfile import ZipFile

    from app.technical_query_docx import render

    item = _query_with_contract(
        monkeypatch,
        "What insurance certificate validity applies to subcontractors?",
        "Painting of tanks is by the Contractor.",
    )
    quote = "Painting of tanks is by the Contractor."
    monkeypatch.setattr(
        "app.search.search",
        lambda q, **k: {
            "hits": [
                {
                    "document_id": "con-a",
                    "page_start": 4,
                    "page_end": 4,
                    "text": quote,
                    "score": 1.0,
                    "rerank_score": 0.4123,
                }
            ]
        },
    )
    got = tq.prepare_evidence(item["id"], frozenset({"con-a"}), "u1", True, False, "u1")
    coverage = got["evidence_coverage"]
    assert coverage["matching_passages"] == 0 and coverage["top_rerank_score"] == 0.412
    assert (
        "likely_not_covered" not in coverage and "not_covered_line" not in coverage
    )  # no verdict from the key-term overlap
    assert (
        got["evidence"][0]["match_ok"] == 0
        and got["evidence"][0]["locator"] is None
        and got["evidence"][0]["rank_score"] == 0.4123
    )
    tq.add_draft(item["id"], "Draft.", [], [], "u1", "u1", True, False)
    word = (
        ZipFile(render(tq.get(item["id"], "u1", True, False), tmp_path / "n.docx"))
        .read("word/document.xml")
        .decode()
    )
    assert (
        "not covered" not in word.casefold()
        and "relevance score" in word
        and "0.412" in word
    )


def test_passages_are_ranked_by_the_rerankers_own_score_across_contracts_and_listed_in_that_order(
    monkeypatch,
):
    from app import technical_query_contracts as TC

    on(monkeypatch)
    for d in ("con-a", "con-b", "con-c"):
        hold_contract(d)
    scores = {
        "con-a": (0.30, 9.0),
        "con-b": (0.80, 1.0),
        "con-c": (0.55, 5.0),
    }  # (reranker score, final score with boosts): they disagree

    def fake(question, **kw):
        d = kw["document_id"]
        return {
            "hits": [
                {
                    "document_id": d,
                    "page_start": 1,
                    "page_end": 1,
                    "text": f"text {d}",
                    "rerank_score": scores[d][0],
                    "score": scores[d][1],
                }
            ]
        }

    monkeypatch.setattr("app.search.search", fake)
    got = TC.search_all("a question", frozenset({"con-a", "con-b", "con-c"}))
    assert [h["document_id"] for h in got["hits"]] == [
        "con-b",
        "con-c",
        "con-a",
    ]  # by the reranker's score, not the boosted one


@pytest.mark.parametrize("setting", [settings])
def test_the_new_columns_exist_after_the_schema_runs(setting, monkeypatch):
    on(monkeypatch)
    with db.connect() as conn:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(query_evidence)")}
    assert {"match_count", "match_terms", "match_ok", "locator"} <= columns
