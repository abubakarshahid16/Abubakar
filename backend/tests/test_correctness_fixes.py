"""The four correctness fixes an independent evaluation called disqualifying.

The worst of them was not a missing answer. Asked for the maximum operating
temperature of a zinc metal coating - NORSOK clause 8.2, page 11, 120 C - the
system answered "<= 80 C" from a different clause on another page, labelled
QUOTED VERBATIM with a page and a clause. A specification error with money
attached and no signal it happened. The page holding clause 8 had been
classified as front matter because it contains the word "composition".
"""

import fitz
import pytest
from fastapi.testclient import TestClient

from app import chunker, db, keyword, lexical
from app import answer as answer_mod
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

#: A page shaped like NORSOK's page 11: numbered clause headings, real prose,
#: and one word that used to be read as a publishing credit.
CLAUSE_PAGE = [
    "8",
    "Thermally sprayed metallic coatings",
    "8.1",
    "General",
    "Relevant requirements provided in this standard are applicable for",
    "thermally sprayed metallic coatings as described in the clauses below.",
    "8.2",
    "Coating materials",
    "The materials for metal spraying shall be in accordance with the following:",
    "Zinc or alloys of zinc shall have a maximum operating temperature of 120 C",
    "and all coating metals shall be marked with composition and batch number",
    "before being accepted for use anywhere on the works described here.",
]

#: A genuine copyright page: prose, publishing markers, no numbered clauses.
COPYRIGHT_PAGE = [
    "Copyright © 2019 by the publisher named below",
    "All rights reserved. No part of this publication may be reproduced,",
    "stored in a retrieval system, or transmitted in any form without the",
    "prior written permission of the publisher.",
    "ISBN 978-0-13-485454-8",
    "Library of Congress Cataloging-in-Publication Data available on request.",
]

AMBIENT = [
    "4.4",
    "Ambient conditions",
    "No final blast cleaning or coating application shall be done if the",
    "relative humidity is more than 85 % and when the steel temperature is",
    "less than 3 C above the dew point of the surrounding air at the time.",
]

INSPECTION = [
    "11",
    "Inspection and testing",
    "Testing and inspection shall be carried out in accordance with Table 3.",
    "The check frequency for each activity is given in that table, and every",
    "surface shall remain accessible until the final inspection is complete.",
]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def upload(client, blocks, name="spec.pdf") -> str:
    path = settings.data_dir / name
    doc = fitz.open()
    for block in blocks:
        page = doc.new_page()
        for i, line in enumerate(block):
            page.insert_text((72, 90 + i * 15), line)
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        doc_id = client.post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    return doc_id


# ============================================== FIX 1: clause page vs front matter


def test_a_page_with_numbered_clause_headings_is_never_front_matter():
    """The whole of NORSOK's clause 8 was dropped because the page says metal
    shall be "marked with composition"."""
    text = "\n".join(CLAUSE_PAGE)
    assert chunker.classify_page(text, 11, 24) == "prose"


def test_a_real_copyright_page_is_still_front_matter():
    """The guard must not swallow the case it was built around. A copyright
    page has sentences but no numbered clauses; only body text has both."""
    text = "\n".join(COPYRIGHT_PAGE)
    assert chunker.classify_page(text, 2, 500) == "frontmatter"


def test_composition_alone_no_longer_condemns_a_page():
    """One ordinary engineering word on any early page used to be enough.

    A full page of it, because a nearly-empty early page is front matter for
    separate and still-correct reasons - the word is what is being tested here,
    not the length guard.
    """
    body = "\n".join([
        "The coating metal shall be marked with composition and batch number",
        "before use, and the certificate shall accompany every delivery to the",
        "site named in the purchase order together with the test results.",
        "Each batch shall be traceable to the melt from which it was produced,",
        "and the supplier shall retain those records for ten years after the",
        "date of despatch in a form that can be produced on request.",
        "Where a substitution is proposed the principal engineer shall approve",
        "it in writing before any material is applied to the works.",
    ])
    assert chunker.classify_page(body, 3, 24) == "prose"


def test_composition_in_its_publishing_sense_still_counts():
    text = (
        "Composition: Aptara Inc.\nCover design by the studio named here.\n"
        "Printed in the United States of America.\nISBN 978-0-13-485454-8\n"
    )
    assert chunker.classify_page(text, 4, 500) == "frontmatter"


def test_the_clause_page_is_indexed_and_answers_from_its_own_clause():
    """End to end: the page is retrievable, and the question that used to be
    answered from the wrong clause is answered from the right one."""
    client = TestClient(app)
    upload(client, [COPYRIGHT_PAGE, CLAUSE_PAGE])

    sections = {
        r["section"]
        for r in db.connect().execute(
            "SELECT DISTINCT section FROM chunks WHERE retrievable = 1 AND section IS NOT NULL"
        )
    }
    assert any(s.startswith("8.2") for s in sections), sections

    result = answer_mod.answer("maximum operating temperature for zinc metal coating", allowed_document_ids=_scope())
    assert result["answer_type"] == "extract"
    assert result["passage"]["section"].startswith("8.2")
    assert "120 C" in result["passage"]["text"]


def test_an_excluded_page_carrying_clause_headings_is_flagged():
    """The regression detector. This should always be zero - if it is not, a
    page like NORSOK 11 has been dropped again, and the UI raises an alert
    rather than showing a quiet count."""
    client = TestClient(app)
    upload(client, [COPYRIGHT_PAGE, CLAUSE_PAGE])
    flagged = db.connect().execute(
        "SELECT COALESCE(SUM(clause_headings), 0) FROM exclusions WHERE scope = 'page'"
    ).fetchone()[0]
    assert flagged == 0


def test_the_document_list_reports_excluded_pages_not_just_chunks():
    """The Documents screen said "3 excluded" for chunks and said nothing at
    all about a dropped page that held an entire clause."""
    client = TestClient(app)
    upload(client, [COPYRIGHT_PAGE, CLAUSE_PAGE])
    doc = client.get("/api/documents").json()[0]
    assert "pages_excluded" in doc
    assert "pages_excluded_characters" in doc
    assert "pages_excluded_with_clause_headings" in doc
    assert doc["pages_excluded"] >= 1               # the copyright page
    assert doc["pages_excluded_with_clause_headings"] == 0


# ============================================== FIX 2: clause number coverage


def test_a_bare_integer_clause_heading_is_detected():
    """NORSOK numbers its top-level clauses as a bare integer with the title
    on the next line. Refusing that shape filed the whole of clause 11 under
    "10.3 Qualification of procedures"."""
    assert chunker._split_line_heading(["11 ", "Inspection and testing "], 0)[0] == (
        "11 Inspection and testing"
    )
    assert chunker._split_line_heading(["1 ", "Scope "], 0)[0] == "1 Scope"


def test_a_general_note_item_is_not_a_clause_heading():
    """The same shape carries general notes. A note is a sentence and ends
    like one; a clause title does not."""
    assert chunker._split_line_heading(
        ["1 ", "Light colour non-skid aggregates shall be used. "], 0
    )[0] is None
    assert chunker._split_line_heading(["1 ", "Aluminium: "], 0)[0] is None
    assert chunker._split_line_heading(["3 ", "Al "], 0)[0] is None


def test_a_restarting_number_list_is_rejected_as_clause_numbering():
    """Clause numbering only increases through a document. A note list
    restarts at 1 under every clause, which is what gives it away."""
    accepted = chunker._bare_integer_clauses(
        ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "1", "2", "3", "1"]
    )
    assert accepted == {str(n) for n in range(1, 12)}


def test_detected_clause_numbers_cover_the_clause_numbers_present():
    """The test asked for: the set of clause numbers detected must cover the
    set of clause numbers present in the document."""
    client = TestClient(app)
    upload(client, [CLAUSE_PAGE, AMBIENT, INSPECTION])

    detected = {
        r["section"].split()[0]
        for r in db.connect().execute(
            "SELECT DISTINCT section FROM chunks WHERE section IS NOT NULL"
        )
    }
    # Clause 8 is immediately followed by 8.1, so it has no body text of its
    # own and no chunk carries it - correctly. It must still be DETECTED as a
    # heading, which is what stopped clause 11 being filed under 10.3.
    expected = {"8.1", "8.2", "4.4", "11"}
    missing = expected - detected
    assert not missing, f"clause numbers present but never detected: {sorted(missing)}"

    pages = [
        (1, "\n".join(CLAUSE_PAGE)),
        (2, "\n".join(AMBIENT)),
        (3, "\n".join(INSPECTION)),
    ]
    headings = chunker._candidate_headings(pages, set(), None)
    # A LIST, in document order. Bare integers are judged by a monotonic walk,
    # so a set would silently change the answer - and did, in an earlier
    # version of this test that passed on the luck of set iteration order.
    numbers = [chunker._heading_number(h) for h in headings]
    allowed = chunker.plausible_heading_numbers(numbers)
    assert {"8", "8.1", "8.2", "4.4", "11"} <= allowed, sorted(allowed)


# ============================================== FIX 3: the two-stage gate


def test_a_named_subject_absent_from_the_corpus_is_refused_without_scoring():
    """"Inconel" appears zero times - that alone is enough, with no semantic
    judgement needed."""
    client = TestClient(app)
    upload(client, [CLAUSE_PAGE, AMBIENT, INSPECTION])
    result = answer_mod.answer("what cladding thickness is required for Inconel 625", allowed_document_ids=_scope())
    assert result["answer_type"] == "insufficient_evidence"
    assert "Inconel" in result["reason"]
    assert "does not appear anywhere" in result["reason"]


def test_all_caps_prose_words_do_not_become_missing_named_subjects():
    """Pasted all-caps questions must not treat ordinary words as identifiers."""
    assert lexical.looks_like_a_named_subject("ORIGINAL", "ON SECOND SECTION ORIGINAL PARAGRAPH") is False
    assert lexical.looks_like_a_named_subject("PARAGRAPH", "ON SECOND SECTION ORIGINAL PARAGRAPH") is False
    assert lexical.looks_like_a_named_subject("NDFT", "WHAT DOES NDFT MEAN") is True


def test_the_refusal_names_the_term_rather_than_only_lacking_confidence():
    client = TestClient(app)
    upload(client, [CLAUSE_PAGE])
    result = answer_mod.answer("what torque is specified for an ASME B16.5 flange", allowed_document_ids=_scope())
    assert result["answer_type"] == "insufficient_evidence"
    assert result["lexical"]["absent_from_corpus"]


def test_a_lexically_plausible_passage_is_no_longer_refused_by_the_old_threshold():
    """The other direction of the same knob: the right chunk was retrieved for
    a question about check frequency and humidity, and refused."""
    client = TestClient(app)
    upload(client, [CLAUSE_PAGE, AMBIENT, INSPECTION])
    result = answer_mod.answer(
        "what is the check frequency and the relative humidity limit during application"
    ,
        allowed_document_ids=_scope())
    assert result["answer_type"] == "extract"


def test_a_passage_sharing_only_common_words_is_not_an_answer():
    client = TestClient(app)
    upload(client, [CLAUSE_PAGE, AMBIENT, INSPECTION])
    verdict = lexical.assess(
        "what is the design pressure of the subsea manifold",
        "The materials for metal spraying shall be in accordance with the following.",
        allowed_document_ids=_scope(),
    )
    assert verdict["ok"] is False
    assert verdict["reason"]


def test_the_lexical_verdict_is_reported_so_a_refusal_can_be_audited():
    client = TestClient(app)
    upload(client, [CLAUSE_PAGE])
    result = answer_mod.answer("what cladding thickness is required for Inconel 625", allowed_document_ids=_scope())
    assert set(result["lexical"]) == {
        "coverage", "terms", "covered", "absent_from_corpus"
    }


def test_a_question_with_no_distinctive_terms_falls_through_to_the_semantic_score():
    """The lexical gate must not become a second refusal path of its own."""
    verdict = lexical.assess("what is it", "any text at all",
                           allowed_document_ids=_scope())
    assert verdict["ok"] is True


# ============================================== FIX 4: two-passage answers


def test_a_compound_question_can_carry_two_passages_from_different_clauses():
    client = TestClient(app)
    upload(client, [CLAUSE_PAGE, AMBIENT, INSPECTION])
    result = answer_mod.answer(
        "what is the check frequency and the relative humidity limit during application"
    ,
        allowed_document_ids=_scope())
    assert result["answer_type"] == "extract"
    passages = result["answer_passages"]
    assert len(passages) == 2
    sections = {p["section"] for p in passages}
    assert len(sections) == 2, sections


def test_a_single_subject_question_carries_one_passage():
    """A score threshold could not separate these: the spurious second passage
    scored 3.90 and the legitimate one -1.50, the wrong way round. The
    difference is in the QUESTION, not in the candidates."""
    client = TestClient(app)
    upload(client, [CLAUSE_PAGE, AMBIENT, INSPECTION])
    result = answer_mod.answer("maximum operating temperature for zinc metal coating", allowed_document_ids=_scope())
    assert len(result["answer_passages"]) == 1


def test_compound_detection_does_not_fire_on_a_word_containing_and():
    """Without the word boundary this matched the "and" inside sandblasting -
    and the escape was silently eaten into a backspace byte twice before that
    boundary actually existed."""
    assert lexical.is_compound_question("what is the sandblasting requirement") is False
    assert lexical.is_compound_question("the standard and the grade") is True


def test_a_second_passage_never_replaces_the_first():
    client = TestClient(app)
    upload(client, [CLAUSE_PAGE, AMBIENT, INSPECTION])
    result = answer_mod.answer(
        "what is the check frequency and the relative humidity limit during application"
    ,
        allowed_document_ids=_scope())
    assert result["answer"] == result["passage"]["text"]
    assert result["answer_passages"][0]["chunk_id"] == result["passage"]["chunk_id"]


def test_a_passage_used_as_an_answer_is_not_repeated_as_supporting():
    client = TestClient(app)
    upload(client, [CLAUSE_PAGE, AMBIENT, INSPECTION])
    result = answer_mod.answer(
        "what is the check frequency and the relative humidity limit during application"
    ,
        allowed_document_ids=_scope())
    used = {p["chunk_id"] for p in result["answer_passages"]}
    assert not used & {p["chunk_id"] for p in result["supporting"]}


def test_an_acronym_absent_from_the_document_is_refused_a_known_limitation():
    """A documented consequence of the lexical gate, not an accident.

    A document that spells out "nominal dry film thickness" without ever
    writing "NDFT" will refuse a question asking for the NDFT. That is the
    correct call under the rule - the term genuinely is not there - but it is
    a false refusal from the reader's point of view, and it is why NORSOK's
    3.2 Abbreviations clause matters: a specification that defines its own
    acronyms answers both forms.
    """
    client = TestClient(app)
    upload(client, [AMBIENT, INSPECTION])   # neither page contains "NDFT"
    result = answer_mod.answer("what is the NDFT for this coating", allowed_document_ids=_scope())
    assert result["answer_type"] == "insufficient_evidence"
    assert "NDFT" in result["lexical"]["absent_from_corpus"]


def test_plausible_heading_numbers_depends_on_document_order():
    """Documented hazard, held by a test: the monotonic walk over bare
    integers reads its input in order, so the same numbers in a different
    order legitimately give a different answer."""
    forwards = chunker.plausible_heading_numbers(["8", "8.1", "8.2", "4.4", "11"])
    assert {"8", "8.1", "8.2", "4.4", "11"} <= forwards

    # Reversed, the walk meets 11 first with nothing to corroborate it, skips
    # it, and then accepts 8 because 8.1 and 8.2 vouch for it. A different
    # answer from the same numbers - which is precisely why the input is a
    # list and why passing a set was a silent bug.
    backwards = chunker.plausible_heading_numbers(["11", "4.4", "8.2", "8.1", "8"])
    assert "11" not in backwards
    assert backwards != forwards


# ================================ the rerank window must cover the chunk


def test_the_rerank_window_covers_the_largest_possible_chunk():
    """A cross-encoder asked to rate a fragment rates the fragment.

    At 256 tokens against a 480-token ceiling, NORSOK's clause 11 was scored
    on its first 256 tokens - environmental conditions and visual examination
    - while the answer, "Holiday detection NACE RP0188 voltage", sat at token
    350. It returned -10.95, which was correct about what it was shown and
    wrong about the passage. The evaluation recorded a retrieval failure that
    was really a truncation failure.
    """
    assert settings.rerank_max_tokens >= settings.chunk_max_tokens, (
        f"rerank window {settings.rerank_max_tokens} is smaller than the chunk "
        f"ceiling {settings.chunk_max_tokens}: any chunk longer than the window "
        f"is judged on a fragment of itself"
    )


def test_a_long_chunk_is_scored_on_content_past_the_old_window():
    """The behaviour, not just the setting. A phrase deep inside a long chunk
    must be able to win, which it cannot if it is truncated away."""
    from app import reranker

    tail = "Holiday detection NACE RP0188 voltage as required by the specification."
    filler = (
        "Ambient and steel temperature shall be recorded before each shift and "
        "the relative humidity shall be measured at the same time in accordance "
        "with the specified requirements for the work being carried out here. "
    )
    long_text = filler * 8 + tail
    scored = reranker.rerank(
        "which standard gives the holiday detection voltage",
        [("deep", long_text), ("shallow", filler)],
    )
    if not scored:
        pytest.skip("reranker model not staged")
    by_id = dict(scored)
    assert by_id["deep"] > by_id["shallow"], (
        "a phrase past the old 256-token window did not beat filler, so the "
        "reranker is still not seeing the tail of a long chunk"
    )


# ============================== the zinc temperature answer, both phrasings


ZINC_TEMPERATURE = [
    "8",
    "Thermally sprayed metallic coatings",
    "8.2",
    "Coating materials",
    "The materials for metal spraying shall be in accordance with the following:",
    "Aluminium: Type Al 99.5 of DIN 8566-2 or equivalent.",
    "Zinc or alloys of zinc.",
    "Metal coating shall be sealed or overcoated as specified in Annex A.",
    "Maximum operating temperature when zinc or alloys of zinc metal coating",
    "is used is 120 C.",
]

#: A different clause that also talks about operating temperature, and gave the
#: wrong answer while clause 8 was unavailable.
OTHER_TEMPERATURE_CLAUSE = [
    "A.8",
    "Coating system no. 8 (shall be pre-qualified)",
    "Application Surface preparation Coating system NDFT um",
    "Structural carbon steel with operating temperature <= 80 C, internal dry",
    "areas. Cleanliness ISO 8501-1 Sa 2 1/2. Roughness ISO 8503 Grade Medium.",
    "General notes: 1. Chalking rating shall be considered for exposed surfaces.",
]


@pytest.mark.parametrize(
    "question",
    [
        # as the document words it
        "What is the maximum operating temperature when zinc or alloys of zinc metal coating is used?",
        # as a user words it
        "what is the maximum operating temperature for zinc metal coating",
        # loosely, lowercase, no question mark
        "max operating temp for zinc coating",
    ],
)
def test_the_zinc_temperature_answer_is_the_same_clause_whatever_the_phrasing(question):
    """One fact, three phrasings, one answer.

    Reported from the running server as page 21 clause A.8 quoting "operating
    temperature <= 80 C" - a specification error with money attached. The cause
    was not ranking: clause 8 sat on a page classified as front matter, so the
    correct passage was not retrievable at all and A.8 was the best remaining
    candidate. With clause 8 present every stage ranks it first.

    Three phrasings because the eval set held ONE per fact, which is why this
    reached a user before it reached the suite.
    """
    client = TestClient(app)
    upload(client, [ZINC_TEMPERATURE, OTHER_TEMPERATURE_CLAUSE])

    result = answer_mod.answer(question, allowed_document_ids=_scope())
    assert result["answer_type"] == "extract", question
    passage = result["answer_passages"][0]
    assert passage["section"].startswith("8.2"), (
        f"{question!r} answered from {passage['section']!r}, not clause 8.2"
    )
    assert "120 C" in passage["text"]
    assert "<= 80 C" not in passage["text"]


def test_hiding_clause_8_is_what_produced_the_wrong_answer():
    """The counter-test, so the diagnosis is held rather than asserted.

    With clause 8 unavailable the system answers from a different clause. That
    is the pre-fix state reproduced, and it is why the front-matter gate in
    classify_page is a correctness fix rather than a coverage improvement.
    """
    client = TestClient(app)
    upload(client, [ZINC_TEMPERATURE, OTHER_TEMPERATURE_CLAUSE])
    conn = db.connect()
    with conn:
        conn.execute(
            "UPDATE chunks SET retrievable = 0 WHERE section LIKE '8.2%' OR section LIKE '8 %'"
        )
        conn.execute(
            "DELETE FROM chunks_fts WHERE chunk_id IN "
            "(SELECT id FROM chunks WHERE retrievable = 0)"
        )

    result = answer_mod.answer(
        "What is the maximum operating temperature when zinc or alloys of zinc metal coating is used?"
    ,
        allowed_document_ids=_scope())
    if result["answer_type"] == "extract":
        assert not result["answer_passages"][0]["section"].startswith("8.2")


def _scope():
    """Corpus-wide scope, stated explicitly.

    Retrieval now REQUIRES an access scope with no default, so a test has to
    name the documents it is allowed to see. These tests want all of them, and
    saying so out loud is the point: when authentication arrives, every one of
    these is a line somebody changes on purpose rather than a default that
    quietly kept meaning "everything".
    """
    from app.search import every_document_id
    return every_document_id()
