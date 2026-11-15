"""Chapters of a rule book for the nine-role reviewer (SPEC C). INVENTED books only; pure code, no database, no model."""

from __future__ import annotations

import hashlib
import sqlite3

import pytest

from app import agent_review_standards as S
from app import nine_chapters as NC

BODY = "The invented item shall be arranged as stated in this invented clause of the invented book."


def _pages(*texts):
    return [(i, t) for i, t in enumerate(texts, 1)]


def _para(n=6):
    return "\n".join(f"{BODY} Line {k}." for k in range(n))


def _numbered():
    return _pages(
        "Cover page of the invented book\nForeword by the invented committee",
        f"1 Scope of the book\n{_para()}\n2 Design rules\n{_para()}\n2.1 Frame width\n{_para(30)}\n2.2 Coating depth\n{_para(30)}",
        f"3 Testing\n{_para()}\n3.1 Pressure tests\n{_para(5)}\n4 Marking\n{_para()}",
    )


def _all_text(cb, pages):
    return "\n".join(line for _p, t in pages for line in t.splitlines() if line.strip())


def test_numbered_headings_the_front_matter_is_not_a_chapter_and_every_other_line_is_in_exactly_one_chapter():
    pages = _numbered()
    cb = NC.cut("b1", pages, max_tokens=100_000)
    assert cb.cut_by == "heading" and cb.note is None
    assert cb.front_matter_chars > 0 and cb.front_matter_pages == (1,)  # cover and foreword: counted, never a chapter
    seen = []
    for c in cb.chapters:
        for k in range(1, len(c.parts) + 1):
            seen.append(cb.text(c.chapter_id, k))
    joined = "\n".join(seen)
    stored = _all_text(cb, pages)
    assert joined == stored.split("\n", 2)[2]  # the stored lines after the two front-matter lines, exactly, nothing cleaned
    assert "Cover page" not in joined and "Foreword" not in joined


def test_the_shallowest_heading_that_fits_is_the_chapter_and_a_chapter_over_the_limit_is_replaced_by_its_sub_headings():
    pages = _numbered()
    whole = NC.cut("b1", pages, max_tokens=100_000)
    ids_whole = [c.chapter_id for c in whole.chapters]
    assert all(c.depth == 1 for c in whole.chapters) and "2" in " ".join(ids_whole) and not any(i.startswith("2.") for i in ids_whole)
    small = NC.cut("b1", pages, max_tokens=1_500)  # 4,500 characters: chapter 2 (6,689) must be replaced by 2.1 and 2.2
    ids_small = [c.chapter_id for c in small.chapters]
    assert ids_small[1:3] == ["2.1", "2.2"] and [c.depth for c in small.chapters[1:3]] == [2, 2]
    assert "1" in ids_small[0] and ids_whole[1] == "2" and small.chapters[1].chars + small.chapters[2].chars == whole.chapters[1].chars


def test_lettered_families_and_appendices_are_chapters_and_small_neighbours_are_one_unit():
    names = "Alpha Bravo Charlie Delta Echo Foxtrot Golf Hotel India Juliet Kilo".split()
    lines = "\n".join(f"UG-{n} Rule about {names[n - 1]}\n{BODY}" for n in range(1, 12))
    pages = _pages(f"UW-1 Welding rule alpha\n{BODY}\nUW-2 Welding rule bravo\n{BODY}", lines, f"Appendix A Invented annex\n{_para(20)}")
    cb = NC.cut("b2", pages, max_tokens=100_000)
    ids = [c.chapter_id for c in cb.chapters]
    assert any(" to " in i for i in ids)  # the tiny paragraphs are joined, each heading kept in `covers`
    assert cb.locate("UG-7") is not None and cb.locate("UG-7") == cb.locate("UG-8") or cb.locate("UG-7") != cb.locate("UW-1")
    assert cb.locate("A.3") == "Appendix A" and cb.locate("") is None and cb.locate("ZZ-9") is None


def test_no_heading_is_read_by_page_windows_with_one_page_repeated_and_the_record_says_so():
    pages = _pages(*[f"{_para(4)}" for _ in range(30)])
    cb = NC.cut("b3", pages, max_tokens=100_000)
    assert cb.cut_by == "page window" and cb.note == "no headings found: read by page windows"
    assert [c.chapter_id for c in cb.chapters] == ["pages 1-12", "pages 12-23", "pages 23-30"]
    assert all(c.cut_by == "page window" for c in cb.chapters)


def test_one_long_chapter_is_split_into_parts_on_page_ends_each_repeating_the_tail_of_the_one_before():
    pages = _pages(f"1 One long chapter\n{_para(30)}", _para(50), _para(50), _para(50))
    cb = NC.cut("b4", pages, max_tokens=2_000)  # 6,000 characters per part
    (c,) = cb.chapters
    assert len(c.parts) >= 4 and all(p.part_of == len(c.parts) for p in c.parts)
    for k, part in enumerate(c.parts, 1):
        text = cb.text(c.chapter_id, k)
        assert part.chars == len(text) and part.text_sha256 == hashlib.sha256(text.encode()).hexdigest()
        if k > 1:
            prev_own = "\n".join(cb._lines[cb._spans[c.chapter_id][k - 2][0] : cb._spans[c.chapter_id][k - 2][1]])
            assert text.startswith(prev_own[-NC.OVERLAP_CHARS :])  # the repeated tail
    ends = [cb._line_page[cb._spans[c.chapter_id][k][1] - 1] for k in range(len(c.parts) - 1)]
    assert ends == sorted(set(ends))  # cut at page ends
    assert all(p.page_from <= p.page_to for p in c.parts)


def test_a_scanned_book_is_cut_from_its_recognised_text_the_same_way():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT)")
    con.execute("CREATE TABLE page_ocr (document_id TEXT, page_no INTEGER, text TEXT, error TEXT)")
    for n, text in enumerate(_numbered(), 1):
        con.execute("INSERT INTO pages VALUES ('scan', ?, '')", (n,))
        con.execute("INSERT INTO page_ocr VALUES ('scan', ?, ?, NULL)", (n, text[1]))
    book = S.read_book(con, "scan")
    assert book.ocr == frozenset({1, 2, 3})
    cb = NC.cut("scan", sorted(book.pages.items()), max_tokens=100_000)
    assert cb.cut_by == "heading" and len(cb.chapters) >= 3


def test_ids_are_unique_even_when_a_heading_repeats_and_an_empty_book_has_no_chapter():
    pages = _pages(f"1 First section\n{_para()}", f"1 First section\n{_para()}\n2 Second section\n{_para()}")
    cb = NC.cut("b5", pages, max_tokens=100)
    ids = [c.chapter_id for c in cb.chapters]
    assert len(ids) == len(set(ids)) and sum(len(c.parts) for c in cb.chapters) >= len(ids)
    assert NC.cut("b6", [(1, "  \n")], max_tokens=1000).chapters == ()


def test_the_limits_are_the_specs_and_tokens_are_characters_over_three():
    assert (NC.CLAUDE_CALL_TOKENS, NC.LOCAL_CALL_TOKENS, NC.OVERLAP_CHARS, NC.WINDOW_PAGES) == (40_000, 5_000, 1_500, 12)
    assert NC.tokens_of(3000) == 1000 and NC.tokens_of(3001) == 1001


def test_no_book_layout_or_word_list_is_written_in_the_module():
    import pathlib

    src = pathlib.Path(NC.__file__).read_text(encoding="utf-8")
    for name in ("ASME", "SAES", "API-", "NACE", "ISO-", "Section VIII", "pressure vessel"):
        assert name not in src
