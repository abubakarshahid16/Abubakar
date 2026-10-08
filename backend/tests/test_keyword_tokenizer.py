"""Keyword index tokenisation: what is stored and what is asked for must agree.

Audit R1/R2/R3/R4/R7 and ingest F3 (2026-09-27). The FTS tokenizer keeps `.`
`-` `/` `_` inside tokens so identifiers survive, and it therefore also kept
the full stop that ends a sentence: "comply with NACE MR0175." was stored as
`mr0175.`, a question about MR0175 matched nothing, and the lexical gate told
the reader "MR0175 does not appear anywhere in the indexed documents". Every
test here builds a real index through `keyword.index_document` (or the
startup migration) and queries it through the production functions, and each
one is mutation-proven: scripts/mutations/keyword.py M1200-M1212.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db, keyword, lexical
from app.config import settings
from app.main import app


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    keyword.reset_vocabulary_cache()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    keyword.reset_vocabulary_cache()
    db.reset_connection()


def _document(doc_id: str, chunks: list[tuple[str, str]]) -> str:
    """One document and its chunks, [(section, text)], written as the chunker
    would write them (retrievable). Not indexed - callers choose how."""
    conn = db.connect()
    conn.execute(
        """INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,
                                  status, uploaded_at)
           VALUES (?, ?, ?, 1, '/nowhere', 'ready', '2026-09-27T00:00:00Z')""",
        (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}"),
    )
    conn.executemany(
        """INSERT INTO chunks (id, document_id, filename, ordinal, page_start,
                               page_end, section, text, token_count, content_hash)
           VALUES (?, ?, ?, ?, 1, 1, ?, ?, 10, ?)""",
        [(f"{doc_id}-c{i}", doc_id, f"{doc_id}.pdf", i, section, text,
          f"h-{doc_id}-{i}") for i, (section, text) in enumerate(chunks)],
    )
    conn.commit()
    return doc_id


def _indexed(doc_id: str, chunks: list[tuple[str, str]]) -> str:
    _document(doc_id, chunks)
    keyword.index_document(doc_id)
    keyword.reset_vocabulary_cache()
    return doc_id


def _everyone() -> frozenset[str]:
    from app.search import every_document_id
    return every_document_id()


def _hits(question: str) -> set[str]:
    return {h["chunk_id"] for h in keyword.search(
        question, limit=30, allowed_document_ids=_everyone())}


SOUR = ("4.2 Sour Service",
        "Materials in wet H2S service shall comply with NACE MR0175.")
HARD = ("4.3 Hardness",
        "Weld hardness shall not exceed 22 HRC.")
PIPE = ("6.1 Piping",
        "Seamless pipe shall be ASTM A106.")
FILLER = ("1 Scope",
          "This specification covers general requirements for rotating "
          "equipment packages supplied to the site.")


# ------------------------------------------------ R1 / F3: sentence-final terms


def test_a_sentence_final_identifier_is_found_by_its_bare_spelling():
    """"MR0175." / "HRC." / "A106." were stored with the full stop glued on,
    so the reader's spelling never matched. Precondition-checked against a
    control word from the middle of a sentence, so a broken index cannot pass
    this by returning nothing for everything."""
    _indexed("spec", [SOUR, HARD, PIPE, FILLER])
    assert "spec-c3" in _hits("rotating equipment"), "precondition: index works"

    assert "spec-c0" in _hits("MR0175")
    assert "spec-c1" in _hits("HRC")
    assert "spec-c2" in _hits("A106")
    everyone = _everyone()
    for term in ("MR0175", "HRC", "A106", "NACE MR0175"):
        assert keyword.term_occurrences(
            term, allowed_document_ids=everyone) > 0, term


def test_the_query_side_strips_a_trailing_full_stop_the_same_way():
    """The same normaliser on both sides. A question that ends "...HRC." sends
    the term "HRC." - which must ask for the token the index holds."""
    _indexed("spec", [SOUR, HARD, PIPE, FILLER])
    assert "spec-c1" in _hits("Is the limit 22 HRC.")
    assert keyword.term_occurrences(
        "HRC.", allowed_document_ids=_everyone()) > 0


def test_every_phrase_the_builder_quotes_is_normalised_like_the_index():
    """`_escape` is the last step before FTS, and callers other than `search`
    (applicability, the acronym map, a future one) hand it terms that were
    never through `normalise_query`. It must ask for `hrc`, not `hrc.`."""
    _indexed("spec", [SOUR, HARD, PIPE, FILLER])
    scope = _everyone()
    hits = keyword._run_match(
        db.connect(), keyword.build_match_query("HRC."),
        *keyword._scope_clause(None, scope), 10)
    assert [h["chunk_id"] for h in hits] == ["spec-c1"]


def test_index_text_keeps_identifiers_intact():
    """Stripping stops at the edges: inner `.`, `-`, `/` survive, so clause
    numbers, grades and units are still one token each."""
    stored = keyword.index_text(
        "See 5.3.2. Use A-106, API 610, Sa 2½, 10.9 bolts, 3,300 kW, mm/s.")
    body = stored.split("\n")[0]
    for kept in ("5.3.2", "A-106", "API 610", "Sa 2½", "10.9", "3,300", "mm/s"):
        assert kept in body, kept
    assert "5.3.2." not in body and "mm/s." not in body


def test_the_refusal_path_no_longer_calls_a_present_standard_absent():
    """END TO END, the honesty invariant. A corpus that says "comply with NACE
    MR0175." and a question naming MR0175: the lexical gate used to refuse
    with "MR0175 does not appear anywhere in the indexed documents"."""
    _indexed("spec", [SOUR, HARD, PIPE, FILLER])
    everyone = _everyone()

    for question in ("Which standard covers sour service, NACE MR0175?",
                     "Is MR0175 required for sour service?"):
        verdict = lexical.assess(question, SOUR[1],
                                 allowed_document_ids=everyone)
        assert "does not appear anywhere" not in (verdict["reason"] or ""), (
            question, verdict)
        assert not any("MR0175" in t for t in verdict["absent_from_corpus"])
        assert verdict["ok"] is True, verdict

    # NOT VACUOUS: a standard the corpus really does not hold still refuses.
    missing = lexical.assess("Is NACE TM0284 required?", SOUR[1],
                             allowed_document_ids=everyone)
    assert missing["ok"] is False
    assert "does not appear anywhere" in missing["reason"]


# ------------------------------------------------ R3: clause / section numbers


def test_find_designators_keeps_the_whole_dotted_number():
    assert keyword.find_designators("clause 5.3.2 of table 5.1") == [
        "clause 5.3.2", "table 5.1"]


def test_a_clause_question_finds_the_clause_by_its_heading_number():
    """Specs print the number in the heading, not "clause 5.3.2" in the body.
    The designator used to become the required phrase "clause 5", which no
    chunk contains, so the keyword side returned nothing at all."""
    _indexed("spec", [
        ("5.3.2 Vibration Limits",
         "Vibration shall not exceed 3.0 mm/s RMS at the bearing housing."),
        ("5.3.3 Noise", "Noise shall not exceed 85 dBA at one metre."),
        FILLER,
    ])
    assert _hits("what does clause 5.3.2 say about vibration") == {"spec-c0"}
    assert "spec-c0" in _hits("section 5.3.2")


def test_a_bare_section_number_is_preferred_not_required():
    """"section 4" is too common a number to require and the body rarely says
    "section 4"; required, it emptied the keyword side."""
    _indexed("spec", [
        ("4 Materials", "Casing material shall be duplex stainless steel."),
        FILLER,
    ])
    assert "spec-c0" in _hits("section 4 materials")


def test_a_table_designator_is_still_required_and_not_truncated():
    """"table 5.1" must not match a chunk captioned Table 5.2 - the truncated
    capture made both "table 5"."""
    _indexed("spec", [
        ("5 Ratings", "Table 5.1 Pressure ratings for flanges."),
        ("5 Ratings", "Table 5.2 Temperature ratings for flanges."),
    ])
    assert _hits("table 5.1 ratings") == {"spec-c0"}


# ------------------------------------------------ R4: identifier spellings


def test_identifier_spellings_match_each_other():
    """API 610 / API-610 / API610 are one standard. Each spelling in a
    question finds every spelling in the documents."""
    _indexed("a", [("1", "Pumps shall comply with API 610 in full.")])
    _indexed("b", [("1", "Pumps shall comply with API-610 in full.")])
    _indexed("c", [("1", "Pumps shall comply with API610 in full.")])
    every = {"a-c0", "b-c0", "c-c0"}
    for asked in ("API 610 pumps", "API-610 pumps", "API610 pumps"):
        assert _hits(asked) == every, asked
    # the lexical gate counts presence the same way search finds it
    for term in ("API 610", "API-610", "API610"):
        assert keyword.term_occurrences(
            term, allowed_document_ids=_everyone()) == 3, term


def test_a_mixed_separator_code_is_found_through_the_index_alias():
    """"SAES H-101V" tokenises as `saes` + `h-101v`; only the joined alias
    `index_text` writes ("saesh101v") lets "SAES-H-101V" find it."""
    _indexed("s", [("1", "Paint systems per SAES H-101V apply.")])
    assert _hits("SAES-H-101V") == {"s-c0"}


def test_an_identifier_number_alone_does_not_satisfy_the_identifier():
    """Precision: a chunk that has 610 but not API 610 is not an API 610
    passage."""
    _indexed("x", [("1", "Pumps shall comply with API 610 in full."),
                   ("1", "The flange is 610 mm across and pumps are grey.")])
    assert _hits("API 610 pumps") == {"x-c0"}
    q = keyword.build_match_query("API 610 pumps")
    assert '"610"' not in q and "610s" not in q


# ------------------------------------------------ R7: plural folding


def test_singular_and_plural_of_an_ordinary_word_match():
    _indexed("p", [("1", "Centrifugal pumps shall have mechanical seals."),
                   ("2", "Each isolation valve shall be lockable."),
                   FILLER])
    assert "p-c0" in _hits("pump seal")
    # the question's own trailing full stop is stripped BEFORE folding, or
    # "pump." is not a word and gets no plural
    assert "p-c0" in _hits("Do we need a pump.")
    assert "p-c1" in _hits("isolation valves")
    assert keyword.term_occurrences(
        "Valves", allowed_document_ids=_everyone()) > 0


def test_identifiers_and_acronyms_are_never_folded():
    for word in ("HRC", "A106", "WCB", "API", "NDFT", "ASME", "CA6NM"):
        assert keyword.word_forms(word) == [word], word
    assert keyword.word_forms("assembly") == ["assembly", "assemblies"]
    assert keyword.word_forms("flanges") == ["flanges", "flange"]


# ------------------------------------------------ numbers and compounds


def test_a_thousands_separated_number_is_found_with_or_without_commas():
    _indexed("n", [("1", "The motor is rated 3,300 kW continuous."),
                   ("2", "The pump runs at 3300 rpm."), FILLER])
    assert _hits("3300") == {"n-c0", "n-c1"}
    assert _hits("3,300") == {"n-c0", "n-c1"}


def test_a_designator_spelled_with_no_dot_matches_the_document():
    """"system no. 1": the variant's own full stop must be normalised the way
    the index normalised the document's, or the phrase never matches."""
    _indexed("d", [("7", "Coating System No. 1: DFT 250 micrometres."),
                   ("7", "Coating System No. 4: DFT 400 micrometres.")])
    assert _hits("coating system 1 dft") == {"d-c0"}


def test_a_word_inside_a_hyphenated_compound_is_findable():
    _indexed("h", [("1", "Bolts shall be hot-dip galvanized carbon-steel."),
                   FILLER])
    assert "h-c0" in _hits("steel")
    assert "h-c0" in _hits("hot dip")


# ------------------------------------------------ versioning and rebuild


def _write_old_style_index(doc_id: str) -> None:
    """What the pre-version-2 indexer wrote: the raw chunk text."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT id, text, section, filename FROM chunks WHERE document_id = ?",
        (doc_id,)).fetchall()
    conn.executemany(
        """INSERT INTO chunks_fts (text, section, filename, chunk_id, document_id)
           VALUES (?, ?, ?, ?, ?)""",
        [(r["text"], r["section"], r["filename"], r["id"], doc_id) for r in rows])
    conn.commit()


def test_an_index_written_by_older_code_is_detected_and_rebuilt():
    _document("old", [SOUR, FILLER])
    _document("waiting", [HARD])          # chunked, keyword stage not yet run
    _write_old_style_index("old")
    assert keyword.index_version() is None
    assert keyword.index_is_stale() is True
    assert "old-c0" not in _hits("MR0175"), "precondition: the old index misses"

    result = keyword.migrate_index()
    assert result["rebuilt"] is True and result["documents"] == 1
    assert keyword.index_version() == keyword.INDEX_VERSION
    assert keyword.index_is_stale() is False
    assert "old-c0" in _hits("MR0175")
    # only documents already in the index are rebuilt
    assert "waiting-c0" not in _hits("HRC")
    # idempotent
    assert keyword.migrate_index()["rebuilt"] is False


def test_server_startup_rebuilds_a_stale_index():
    _document("old", [SOUR, FILLER])
    _write_old_style_index("old")
    with TestClient(app):
        pass
    assert keyword.index_version() == keyword.INDEX_VERSION
    assert "old-c0" in _hits("MR0175")
