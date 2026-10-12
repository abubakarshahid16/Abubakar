"""A document's own designation is not a term its passages must repeat.

Found on the owner's library 2026-10-02 after batch C: a comparison side asks
"What does SAES-W-017 say about post weld heat treatment?" inside that ONE
standard. The designation counted as a third distinctive term, which pushed
the question over `LONG_QUESTION_TERM_COUNT` and demanded two shared terms
from a page that can only supply the topic (the standard prints its own
number on its cover, not on the page that answers). The right page was
refused: "shares only 1 of the 2 distinctive terms this question needs".

Fix: in a ONE-document scope the document's own designation (by file name) is
credited for every passage of that document. In any wider scope it is not.
"""

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import db, keyword, lexical
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

COVER = [
    "1.1 Scope",
    "This standard SAES-W-017 covers the welding of pressure vessels in all",
    "plants and facilities and supersedes every earlier revision of it.",
]
PWHT_PAGE = [
    "7.4 Thermal treatment",
    "Relieving shall be performed in accordance with the heating and cooling",
    "rates given in Table 4 and the holding temperature shall be maintained",
    "for the duration specified for the material grade.",
]
STRESS_PAGE = [
    "9.2 Residual stress",
    "Residual stress in the weld region is limited by the sequence of passes.",
]
OTHER = ["3.1 Scope", "General requirements for piping systems in onshore service."]
QUESTION = "What does SAES-W-017 say about stress relieving?"


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


def upload(client, blocks, name) -> str:
    path = settings.data_dir / name
    doc = pymupdf.open()
    for block in blocks:
        page = doc.new_page()
        for i, line in enumerate(block):
            page.insert_text((72, 100 + i * 16), line)
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        doc_id = client.post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    return doc_id


PASSAGE = " ".join(PWHT_PAGE)


def test_the_answering_page_passes_inside_its_own_standard():
    """MUTATION TARGET: the standard prints its number on the cover only
    (so the term HAS occurrences and the filename branch is not reached), the
    answering page lacks it, and the page must still pass in a one-document
    scope."""
    client = TestClient(app)
    a = upload(client, [COVER, PWHT_PAGE, STRESS_PAGE], "SAES-W-017.pdf")
    assert keyword.term_occurrences("SAES-W-017", allowed_document_ids=frozenset({a})) > 0

    verdict = lexical.assess(QUESTION, PASSAGE, allowed_document_ids=frozenset({a}))
    assert verdict["ok"] is True, verdict


def test_the_credit_does_not_reach_a_wider_scope():
    """NOT VACUOUS: with two documents in scope a passage gets NO credit for
    a designation it does not print, so the stricter bar still applies."""
    client = TestClient(app)
    a = upload(client, [COVER, PWHT_PAGE, STRESS_PAGE], "SAES-W-017.pdf")
    b = upload(client, [OTHER], "other-spec.pdf")

    verdict = lexical.assess(QUESTION, PASSAGE, allowed_document_ids=frozenset({a, b}))
    assert verdict["ok"] is False, verdict


def test_an_unrelated_passage_in_the_one_document_scope_still_fails():
    """NOT VACUOUS: the credit is for the designation only. A passage that
    shares no topic term with the question is still refused."""
    client = TestClient(app)
    a = upload(client, [COVER, PWHT_PAGE, STRESS_PAGE, OTHER], "SAES-W-017.pdf")

    verdict = lexical.assess(
        QUESTION, "General requirements for piping systems in onshore service.",
        allowed_document_ids=frozenset({a}))
    assert verdict["ok"] is False, verdict


def test_a_standard_held_as_two_files_is_credited_in_both():
    """The real comparison side holds every document of a standard (a re-issue
    or a duplicate upload). Two files, same designation: still credited."""
    client = TestClient(app)
    a = upload(client, [COVER, PWHT_PAGE, STRESS_PAGE], "SAES-W-017.pdf")
    b = upload(client, [COVER, PWHT_PAGE, STRESS_PAGE], "SAES-W-017 _1_.pdf")

    verdict = lexical.assess(QUESTION, PASSAGE, allowed_document_ids=frozenset({a, b}))
    assert verdict["ok"] is True, verdict


def test_one_foreign_file_in_scope_removes_the_credit():
    """NOT VACUOUS: the credit needs EVERY document in scope to carry the
    designation."""
    client = TestClient(app)
    a = upload(client, [COVER, PWHT_PAGE, STRESS_PAGE], "SAES-W-017.pdf")
    b = upload(client, [OTHER], "SAES-W-099.pdf")

    verdict = lexical.assess(QUESTION, PASSAGE, allowed_document_ids=frozenset({a, b}))
    assert verdict["ok"] is False, verdict


# ---- end to end, through the real comparison path --------------------------
from app import chat_comparison  # noqa: E402


def _pwht(n):
    return [
        f"{n}.1 Post Weld Heat Treatment (PWHT)",
        f"Post weld heat treatment (PWHT) of joint type {n} shall be carried out",
        "under a written procedure approved before work starts, with the",
        f"heat treatment record for joint {n} kept for the owner.",
    ]


def _plain(n, word):
    return [
        f"{n}.1 {word.title()} Requirements",
        f"The {word} for item {n} shall be installed as shown on the drawing,",
        "inspected by the site engineer and recorded in the daily log.",
    ]


def test_compare_answers_for_a_standard_that_prints_its_number_on_the_cover_only():
    """The owner's case: the standard prints its number once, on its cover;
    the answering pages never repeat it. Run through `chat_comparison.compare`
    exactly as the chat does."""
    client = TestClient(app)
    cover = ["1.1 Scope", "This standard STD-K-118 covers welding of vessels and",
             "supersedes every earlier revision of it."]
    pages = [cover] + [_pwht(i) for i in range(3)] + [_plain(i, "gasket") for i in range(20)]
    target = upload(client, pages, "STD-K-118.pdf")
    others = [upload(client, [_plain(i, w) for i in range(22)], f"STD-X-20{k}.pdf")
              for k, w in enumerate(("bolting", "painting", "valve", "pump"))]
    everything = frozenset({target, *others})

    out = chat_comparison.compare(
        "what do the welding standards say about post weld heat treatment",
        [("STD-K-118", frozenset({target}))], tier="extract",
        allowed_document_ids=everything, progress_id=None, model=None, history="",
        topic="post weld heat treatment")
    side = out["comparison"]["sides"][0]
    assert side["answer_type"] != "insufficient_evidence", side
    assert "Not found" not in (side["text"] or "")


# ---- a designation the identifier pattern only half-matches ----------------
LONG_NAME = "NACE-MR0175-ISO15156-specification"


def _long_cover():
    # the pages never print the file name, as in the owner's library
    return ["1.1 Scope", "This document is the reference text for materials",
            "in sour service and supersedes every earlier revision of it."]


def test_a_long_designation_matched_in_part_is_still_credited():
    """Found on the owner's library (2026-10-02): the identifier pattern
    matches only the tail `MR0175-ISO15156-specification` of the file name
    `NACE-MR0175-ISO15156-specification`, while the word scan keeps the whole
    name. The tail never equalled the designation, was reported "not
    anywhere in the indexed documents", and a side with five strong hits was
    refused. The tail IS the standard's own name, so it is credited too."""
    client = TestClient(app)
    pages = [_long_cover()] + [_pwht(i) for i in range(3)] + [_plain(i, "gasket") for i in range(20)]
    target = upload(client, pages, f"{LONG_NAME}.pdf")
    others = [upload(client, [_plain(i, w) for i in range(22)], f"STD-X-30{k}.pdf")
              for k, w in enumerate(("bolting", "painting", "valve", "pump"))]
    everything = frozenset({target, *others})

    out = chat_comparison.compare(
        "what do the welding standards say about post weld heat treatment",
        [(LONG_NAME, frozenset({target}))], tier="extract",
        allowed_document_ids=everything, progress_id=None, model=None, history="",
        topic="post weld heat treatment")
    side = out["comparison"]["sides"][0]
    assert side["answer_type"] != "insufficient_evidence", side
    assert "Not found" not in (side["text"] or "")


def test_a_fragment_of_another_standards_name_gets_no_credit():
    """NOT VACUOUS: a fragment is credited only when it is part of the name of
    EVERY document in scope; a name that belongs to another standard is not."""
    client = TestClient(app)
    a = upload(client, [_long_cover(), _pwht(1), _pwht(2)], f"{LONG_NAME}.pdf")
    verdict = lexical.assess(
        "What does STD-Q-999 say about post weld heat treatment?",
        "Post weld heat treatment (PWHT) of joint type 1 shall be carried out",
        allowed_document_ids=frozenset({a}))
    assert verdict["ok"] is False
    assert "STD-Q-999" in verdict["absent_from_corpus"]
