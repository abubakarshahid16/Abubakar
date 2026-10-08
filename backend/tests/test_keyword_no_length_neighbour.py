"""A word with no length-neighbour in the vocabulary gets no correction.

Found by a full-suite run (2026-09-26): `difflib.get_close_matches` raises on
n=0, and `fuzzy_corpus_match` passed n=len(near) with `near` empty - so a
question containing such a word crashed the whole search instead of simply
having no spelling correction.
"""
from app import keyword


def test_a_word_with_no_length_neighbour_gets_no_correction(monkeypatch):
    monkeypatch.setattr(keyword, "term_occurrences", lambda *a, **k: 0)
    monkeypatch.setattr(keyword, "vocabulary", lambda *a, **k: ["ab"])
    assert keyword.fuzzy_corpus_match("everything", allowed_document_ids=frozenset({"d"})) is None
