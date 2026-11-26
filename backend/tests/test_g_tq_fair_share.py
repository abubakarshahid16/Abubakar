"""Every contract part gets a fair share of a technical query's evidence (lead-4's score of 26 Nov 2026: the 4 misses were parts never
listed while one part filled up to 8 of 14 places). Invented hits only."""

from __future__ import annotations

from app import technical_query_contracts as C


def hit(doc, score, page=1):
    return {
        "document_id": doc,
        "rerank_score": score,
        "page_start": page,
        "text": f"invented {doc} {page}",
    }


def test_every_part_with_a_hit_is_listed_even_when_one_part_scores_higher_everywhere():
    big = [hit("big", 9 - n * 0.1, n) for n in range(8)]
    small = [[hit(f"part{n}", -5.0 - n)] for n in range(6)]
    got = C.fair_share([big, *small])
    assert {h["document_id"] for h in got} == {"big", *(f"part{n}" for n in range(6))}
    assert (
        sum(1 for h in got if h["document_id"] == "big") == C.PER_PART_LISTED
    )  # never 8 of one part
    assert [h["rerank_score"] for h in got] == sorted(
        (h["rerank_score"] for h in got), reverse=True
    )  # the reranker's order


def test_the_list_never_passes_its_cap_and_keeps_each_parts_best():
    parts = [
        [hit(f"p{n}", 1.0 - n * 0.01, 1), hit(f"p{n}", 0.5 - n * 0.01, 2)]
        for n in range(40)
    ]
    got = C.fair_share(parts)
    assert len(got) == C.MAX_PASSAGES
    assert all(
        h["page_start"] == 1 for h in got
    )  # the best of each part before any second passage


def test_a_part_with_no_hit_adds_nothing():
    assert C.fair_share([[], [hit("a", 1.0)]]) == [hit("a", 1.0)]


# ---- a passage is quoted by what stands verbatim on its own pages, never dropped for its reading order
from app import db  # noqa: E402
from app.technical_queries import _verbatim_quote  # noqa: E402

from .test_technical_queries import temp_storage  # noqa: E402, F401 - the fixture is used by name

PAGE1 = "Invented header. 4.2 Invented Pumps The invented pumps shall be of the invented centrifugal type with invented mechanical seals"
PAGE2 = "and invented bearings. Invented table: A 12 B 14 Invented footer."


def _pages():
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES ('c1','c.pdf',?,1,'c.pdf','ready','2026-01-01')",
            ("f" * 64,),
        )
        for n, text in ((1, PAGE1), (2, PAGE2)):
            conn.execute(
                "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES ('c1',?,?,?,0,1)",
                (n, text, len(text)),
            )


def test_a_passage_running_over_two_pages_is_kept_whole():
    _pages()
    passage = "The invented pumps shall be of the invented centrifugal type with invented mechanical seals and invented bearings."
    with db.connect() as conn:
        assert _verbatim_quote(conn, "c1", 1, 2, passage) == passage


def test_a_passage_in_another_reading_order_is_quoted_by_its_longest_verbatim_run():
    _pages()
    reordered = "A B 12 14 Invented table: The invented pumps shall be of the invented centrifugal type with invented mechanical seals"
    with db.connect() as conn:
        got = _verbatim_quote(conn, "c1", 1, 2, reordered)
    assert (
        got
        == "The invented pumps shall be of the invented centrifugal type with invented mechanical seals"
    )


def test_a_passage_with_no_long_verbatim_run_is_not_quoted():
    _pages()
    with db.connect() as conn:
        assert (
            _verbatim_quote(
                conn,
                "c1",
                1,
                2,
                "Nothing of this stands on the invented pages at all, not one long run.",
            )
            is None
        )
