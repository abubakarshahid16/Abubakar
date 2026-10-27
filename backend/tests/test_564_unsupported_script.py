"""#564: a page written mostly in Arabic script is held out of retrieval with a
named reason and is counted as not read, never as "searched, nothing found".

Invented text only; no model, no socket.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import chunker as ch
from app import db, page_ledger, quality, unsupported_script
from app.config import settings

NOW = "2026-10-27T00:00:00Z"

ENGLISH = (
    "Marking shall be applied to every component before it leaves the shop. "
    "Marks shall be legible and durable after heat treatment. "
) * 3
#: Invented Arabic sentences (ordinary words, no document text).
ARABIC = (
    "يجب أن يكون ضغط التصميم للوعاء أعلى من ضغط التشغيل بمقدار كاف. "
    "يجب فحص جميع اللحامات قبل تسليم المعدات إلى الموقع. "
) * 3


def test_an_arabic_paragraph_is_unsupported_and_an_english_one_is_not():
    assert unsupported_script.is_unsupported(ARABIC)
    assert not unsupported_script.is_unsupported(ENGLISH)


def test_one_arabic_word_in_an_english_sentence_holds_nothing_back():
    text = ENGLISH + " الوعاء "
    assert not unsupported_script.is_unsupported(text)


def test_too_little_text_is_never_judged():
    assert unsupported_script.counts("الوعاء") == (6, 6)
    assert not unsupported_script.is_unsupported("الوعاء")


def test_the_share_is_of_letters_only_digits_and_punctuation_do_not_count():
    arabic, letters = unsupported_script.counts("12345 ... --- ابجد")
    assert (arabic, letters) == (4, 4)
    numbers_around = "1 2 3 4 5 6 7 8 9 0 " * 20 + "ابجد هوز"
    assert not unsupported_script.is_unsupported(numbers_around)


@pytest.mark.parametrize(
    ("arabic_words", "english_words", "held"),
    [(7, 3, True), (3, 7, False)],
)
def test_the_cut_is_a_majority_of_letters(arabic_words, english_words, held):
    text = " ".join(["ضغطالتصميم"] * arabic_words + ["pressure"] * english_words)
    assert unsupported_script.is_unsupported(text) is held


def test_the_stored_reason_names_the_rule_the_words_and_the_denominator():
    why = unsupported_script.reason(ARABIC)
    assert why.startswith("unsupported_script: language not supported, engineer review")
    arabic, letters = unsupported_script.counts(ARABIC)
    assert f"{arabic} of {letters} letters" in why


@pytest.mark.parametrize("kind", ["prose", "table"])
def test_the_quality_gate_rejects_an_arabic_chunk_by_name(kind):
    verdict = quality.assess(ARABIC, kind)
    assert verdict["ok"] is False
    assert verdict["reasons"][0].startswith(unsupported_script.RULE)


def test_an_english_chunk_is_judged_as_before():
    assert quality.assess(ENGLISH, "prose")["ok"] is True


def test_the_ledger_words_say_why_for_this_rule_and_are_unchanged_for_others():
    mine = unsupported_script.not_reached("not_retrievable", "unsupported_script")
    assert mine.startswith("language not supported, engineer review")
    assert "never saw it" in mine
    other = unsupported_script.not_reached("not_retrievable", "content_quality_gate")
    assert other == (
        "no retrievable chunk covers this page (not_retrievable: content_quality_gate),"
        " so fact extraction never saw it"
    )
    assert "language not supported" not in unsupported_script.not_reached(
        "no_chunk", None
    )


class _WordTokenizer:
    """One token per word: the real tokenizer's files are not needed to chunk invented text."""

    def encode(self, text, add_special_tokens=False):
        return SimpleNamespace(ids=list(range(len(text.split()))))

    def decode(self, ids):
        return " ".join("w" for _ in ids)


def _add_page(conn, page_no, text):
    conn.execute(
        "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
        " VALUES ('d564',?,?,?,0,0)",
        (page_no, text, len(text)),
    )


def test_an_arabic_page_is_excluded_by_name_and_the_ledger_counts_it_as_not_read(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(ch, "get_tokenizer", lambda: _WordTokenizer())
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    try:
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
                "page_count,uploaded_at) VALUES ('d564','sheet.pdf','sha-564',1,'/tmp/x',"
                "'chunking',2,?)",
                (NOW,),
            )
            _add_page(conn, 1, ENGLISH)
            _add_page(conn, 2, ARABIC)
        ch.chunk_document("d564")
        conn = db.connect()
        held = conn.execute(
            "SELECT reason FROM exclusions WHERE document_id='d564'"
        ).fetchall()
        assert [r["reason"].split(":")[0] for r in held] == ["unsupported_script"]
        rules = conn.execute(
            "SELECT scope, rule, page_start FROM exclusions WHERE document_id='d564'"
        ).fetchall()
        assert [(r["scope"], r["rule"], r["page_start"]) for r in rules] == [
            ("page", "page_classified_unsupported_script", 2)
        ]
        spans = conn.execute(
            "SELECT page_start, page_end, retrievable FROM chunks"
            " WHERE document_id='d564' AND retrievable=1"
        ).fetchall()
        # the English page is its own chunk: the Arabic page is not merged into it
        assert [(r["page_start"], r["page_end"]) for r in spans] == [(1, 1)]
        page_ledger.refresh("d564", as_submittal=True)
        rows = {
            r["page_no"]: r
            for r in conn.execute(
                "SELECT page_no, index_status, index_reason, facts_status, facts_reason"
                " FROM page_ledger WHERE document_id='d564'"
            )
        }
        assert rows[1]["index_status"] == "retrievable"
        assert rows[2]["index_status"] == "excluded"
        assert rows[2]["index_reason"] == "page_classified_unsupported_script"
        assert rows[2]["facts_status"] == "not_reached"
        assert rows[2]["facts_status"] in page_ledger.NOT_READ_INTO_FIELDS
        assert rows[2]["facts_reason"].startswith("language not supported")
        assert rows[1]["facts_status"] != "not_reached"
    finally:
        db.reset_connection()
