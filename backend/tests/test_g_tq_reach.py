"""Reach of the technical-query evidence search into one contract: ideas b (wide candidates), c (headings), a (the contract's own words), each behind
its letter of TECHNICAL_QUERY_REACH. Fake search and fake reranker; invented contract text only; no model, no network."""

from __future__ import annotations

from app import db
from app import technical_query_contracts as TC
from app import technical_query_reach as R
from app.config import settings
from tests.test_tq_g_feature_off import (  # noqa: F401 - helpers
    hold_contract,
    on,
    storage,
)

Q = "What coating thickness applies to carbon steel tanks?"


def chunk(doc, n, section, text, context=None, page=1):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO chunks(id,document_id,filename,ordinal,page_start,page_end,section,context,text,token_count,content_hash,retrievable) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
            (
                f"{doc}-{n}",
                doc,
                "c.pdf",
                n,
                page,
                page,
                section,
                context,
                text,
                len(text.split()),
                f"h{doc}{n}",
            ),
        )


class Fake:
    """A fake search that records its calls and answers by what the question holds."""

    def __init__(self, answers):
        self.calls, self.answers = [], answers

    def __call__(self, question, **kw):
        self.calls.append((question, kw))
        for needle, hits in self.answers:
            if needle in question:
                return {"hits": hits}
        return {"hits": []}


def hit(doc, page, text, score=0.5):
    return {
        "document_id": doc,
        "page_start": page,
        "page_end": page,
        "text": text,
        "rerank_score": score,
        "score": score,
    }


def test_the_letters_are_read_from_the_setting_and_unknown_ones_are_ignored(
    monkeypatch,
):
    for value, want in (
        ("", set()),
        ("b", {"b"}),
        ("ABC", {"a", "b", "c"}),
        ("bx9", {"b"}),
        (None, set()),
    ):
        monkeypatch.setattr(settings, "technical_query_reach", value)
        assert R.ideas() == want


def test_with_no_letter_the_search_is_exactly_the_plain_one(monkeypatch):
    on(monkeypatch)
    monkeypatch.setattr(settings, "technical_query_reach", "")
    fake = Fake(
        [
            (
                "coating",
                [hit("con-a", 1, "t1"), hit("con-a", 2, "t2"), hit("con-a", 3, "t3")],
            )
        ]
    )
    got = R.search_contract(Q, "con-a", 2, search_fn=fake)
    assert len(fake.calls) == 1 and fake.calls[0][1] == {
        "limit": 2, "document_id": "con-a", "rerank": True, "dense": True, "allowed_document_ids": frozenset({"con-a"}),
    }  # fmt: skip
    assert [h["text"] for h in got] == ["t1", "t2"]


def test_idea_b_asks_for_a_wide_pool_and_keeps_the_cut_for_after_the_reranker(
    monkeypatch,
):
    on(monkeypatch)
    monkeypatch.setattr(settings, "technical_query_reach", "b")
    fake = Fake(
        [("coating", [hit("con-a", p, f"t{p}", 1.0 - p / 100) for p in range(1, 12)])]
    )
    got = R.search_contract(Q, "con-a", 2, search_fn=fake)
    (call,) = fake.calls
    assert (
        call[1]["candidates"] == R.WIDE_CANDIDATES
        and call[1]["rerank_candidates"] == R.WIDE_SHORTLIST
        and call[1]["limit"] == R.WIDE_KEEP
    )
    assert len(got) == R.WIDE_KEEP and [h["page_start"] for h in got] == list(
        range(1, 9)
    )


def test_idea_c_adds_a_chunk_whose_heading_holds_the_question_terms_and_scores_it_against_the_original_question(
    monkeypatch,
):
    on(monkeypatch)
    monkeypatch.setattr(settings, "technical_query_reach", "c")
    hold_contract("con-a")
    chunk(
        "con-a",
        1,
        "6.1 Surface protection of carbon steel tanks",
        "Items shall receive three coats at 250 microns.",
        page=4,
    )
    chunk("con-a", 2, "9.3 Insurance", "Certificates are due annually.", page=9)
    fake = Fake([("coating", [hit("con-a", 2, "an ordinary body hit", 0.2)])])
    seen = {}

    def rerank(question, items):
        seen["question"], seen["items"] = question, items
        return [(items[0][0], 0.91)]

    got = R.search_contract(Q, "con-a", 2, search_fn=fake, rerank_fn=rerank)
    assert (
        seen["question"] == Q
        and len(seen["items"]) == 1
        and "three coats" in seen["items"][0][1]
    )  # the ORIGINAL question, the heading chunk only
    assert (
        got[0]["text"].startswith("Items shall receive")
        and got[0]["via"] == "heading"
        and got[0]["rerank_score"] == 0.91
    )
    assert all(
        "Insurance" not in (h.get("section") or "") for h in got
    )  # a chunk whose heading holds none of the terms is not brought in


def test_idea_a_widens_the_question_with_the_contracts_own_words_and_ranks_what_it_finds_by_the_original_question(
    monkeypatch,
):
    on(monkeypatch)
    monkeypatch.setattr(settings, "technical_query_reach", "a")
    hold_contract("con-a")
    chunk(
        "con-a",
        1,
        "6 Painting and surface protection",
        "Painting is by the Contractor.",
        page=4,
    )
    chunk(
        "con-a",
        2,
        "1 Definitions",
        'In this Contract "Coating" means the paint system applied to steelwork and equipment.',
        page=1,
    )
    words = R.own_words(db.connect(), "con-a", Q)
    assert "paint" in words  # from the contract's own definition of "Coating"
    assert (
        "coat" not in words and "tank" not in words
    )  # never a word the question already has
    fake = Fake(
        [
            (
                "paint",
                [
                    hit(
                        "con-a",
                        4,
                        "Painting is by the Contractor and the paint system is 250 microns.",
                        0.1,
                    )
                ],
            )
        ]
    )  # only the widened question finds it

    def rerank(question, items):
        assert question == Q  # scored against the ORIGINAL wording
        return [(items[0][0], 0.77)]

    got = R.search_contract(Q, "con-a", 2, search_fn=fake, rerank_fn=rerank)
    assert (
        len(fake.calls) == 2
        and fake.calls[0][0] == Q
        and fake.calls[1][0].startswith(Q + " ")
    )
    assert got[0]["rerank_score"] == 0.77 and got[0]["via"] == "own_words"


def test_a_definition_names_words_for_a_question_term_and_a_chunk_of_another_contract_is_never_read(
    monkeypatch,
):
    on(monkeypatch)
    hold_contract("con-a")
    hold_contract("con-b")
    chunk(
        "con-a",
        1,
        "1 Definitions",
        'In this Contract "Coating" means the protective paint system and primer.',
        page=1,
    )
    chunk("con-b", 1, "Painting of tanks and surface protection", "x", page=1)
    words = R.own_words(db.connect(), "con-a", Q)
    assert {"protective", "paint", "system", "primer"} & set(
        words
    ) and "surface" not in words  # con-b's heading is not con-a's word
    assert (
        R.heading_candidates(db.connect(), "con-a", Q) == []
    )  # con-a has no heading about tanks


def test_search_all_uses_the_reach_and_states_which_ideas_were_on(monkeypatch):
    on(monkeypatch)
    monkeypatch.setattr(settings, "technical_query_reach", "b")
    for d in ("con-a", "con-b"):
        hold_contract(d)
    monkeypatch.setattr(
        "app.search.search",
        lambda q, **kw: {
            "hits": [
                hit(kw["document_id"], p, f"{kw['document_id']} {p}", 0.9 - p / 100)
                for p in range(1, 12)
            ]
        },
    )
    got = TC.search_all(Q, frozenset({"con-a", "con-b"}))
    assert got["coverage"]["reach"] == "b" and len(got["hits"]) == 2 * R.WIDE_KEEP
    monkeypatch.setattr(settings, "technical_query_reach", "")
    plain = TC.search_all(Q, frozenset({"con-a", "con-b"}))
    assert (
        plain["coverage"]["reach"] == "" and len(plain["hits"]) == 2 * TC.PER_CONTRACT
    )


def test_the_search_accepts_a_wider_shortlist_and_defaults_to_the_setting():
    import inspect

    from app import search

    params = inspect.signature(search.search).parameters
    assert params["rerank_candidates"].default is None
    assert (
        "shortlist_size = rerank_candidates or settings.rerank_candidates"
        in inspect.getsource(search.search)
    )
