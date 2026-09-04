"""Acronym expansions harvested from the documents themselves.

A document that spells out "nominal dry film thickness" and never writes NDFT
refused a question asking for the NDFT. The term genuinely was not there, and
the reader was still asking a fair question.

Relying on a glossary clause alone would have looked sufficient on NORSOK,
which has one. It is not sufficient in general: Aramco specifications are
dense with acronyms and a client uploads their own documents, one of which may
have no abbreviations clause at all.
"""

import fitz
import pytest
from fastapi.testclient import TestClient

from app import acronyms, db, keyword, lexical
from app import answer as answer_mod
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

#: Each of the three definition forms, one per page, plus a page that uses the
#: acronym only and a page that uses the full term only.
PARENTHETICAL = [
    "4.4",
    "Film thickness",
    "The nominal dry film thickness (NDFT) shall be measured on every coat",
    "applied to the prepared surface, and the recorded value shall be entered",
    "on the coating procedure specification before the work is accepted.",
]

INVERSE = [
    "4.5",
    "Adhesion testing",
    "The MAWP (maximum allowable working pressure) shall be stated on the",
    "nameplate of every vessel supplied under this specification, together",
    "with the design temperature and the year of manufacture.",
]

GLOSSARY = [
    "3.2",
    "Abbreviations",
    "CPS coating procedure specification CPT coating procedure test",
    "NACE National Association of Corrosion Engineers PWHT post weld heat",
    "treatment SAMSS Saudi Aramco materials system specification",
]

ACRONYM_ONLY = [
    "9.3",
    "Application",
    "The NDFT for the submerged zone shall not be less than 350 um and the",
    "PWHT shall be completed before any coating is applied to the weld area",
    "or to the heat affected zone adjacent to it.",
]

FULL_TERM_ONLY = [
    "9.4",
    "Repair",
    "Where a repair is required the nominal dry film thickness shall be",
    "restored to the value given for the original coating system, and the",
    "post weld heat treatment records shall accompany the repair report.",
]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    acronyms.reset_cache()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()
    acronyms.reset_cache()


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
    acronyms.reset_cache()
    return doc_id


# ------------------------------------------------------------ the validator


def test_the_initials_must_spell_the_acronym():
    """This check is the whole thing. Harvesting the patterns without it gave
    "AB" meaning "show that" and "BC" meaning "e interpret this by the two
    boundary conditions" on the real corpus."""
    assert acronyms.initials_match("NDFT", "nominal dry film thickness")
    assert acronyms.initials_match("CPS", "coating procedure specification")
    assert acronyms.initials_match("PWHT", "post weld heat treatment")

    assert not acronyms.initials_match("AB", "show that")
    assert not acronyms.initials_match("BC", "e interpret this by the two")
    assert not acronyms.initials_match("NDFT", "nominal dry film")
    assert not acronyms.initials_match("CPS", "coating procedure")


def test_function_words_may_be_skipped_but_not_substantive_ones():
    """"National Association of Corrosion Engineers" is NACE, not NAOCE."""
    assert acronyms.initials_match("NACE", "National Association of Corrosion Engineers")
    assert acronyms.initials_match("EPA", "environmental protection agency")
    # a substantive word contributing no letter disqualifies the match
    assert not acronyms.initials_match("NA", "National Corrosion Association")


def test_a_single_letter_is_not_an_abbreviation():
    assert not acronyms.looks_like_acronym("A")
    assert acronyms.looks_like_acronym("AB")
    assert acronyms.looks_like_acronym("SAES")
    assert acronyms.looks_like_acronym("CERT/CC")
    assert not acronyms.looks_like_acronym("coating")


# --------------------------------------------------------------- harvesting


def test_a_parenthetical_definition_is_harvested():
    client = TestClient(app)
    upload(client, [PARENTHETICAL])
    assert "nominal dry film thickness" in acronyms.harvest()["NDFT"]


def test_an_inverse_parenthetical_definition_is_harvested():
    client = TestClient(app)
    upload(client, [INVERSE])
    assert "maximum allowable working pressure" in acronyms.harvest()["MAWP"]


def test_a_glossary_row_is_harvested():
    client = TestClient(app)
    upload(client, [GLOSSARY])
    harvested = acronyms.harvest()
    assert "coating procedure specification" in harvested["CPS"]
    assert "post weld heat treatment" in harvested["PWHT"]


def test_a_capitalised_glossary_expansion_is_harvested():
    """NORSOK's row reads "NACE National Association of Corrosion Engineers",
    and requiring a lowercase expansion missed it."""
    client = TestClient(app)
    upload(client, [GLOSSARY])
    assert any(
        e.startswith("national association") for e in acronyms.harvest().get("NACE", ())
    )


def test_the_map_is_bidirectional():
    client = TestClient(app)
    upload(client, [PARENTHETICAL])
    assert acronyms.equivalents("NDFT") == ["nominal dry film thickness"]
    assert acronyms.equivalents("nominal dry film thickness") == ["NDFT"]


def test_a_term_the_corpus_never_defines_has_no_equivalents():
    client = TestClient(app)
    upload(client, [PARENTHETICAL])
    assert acronyms.equivalents("Inconel") == []
    assert acronyms.equivalents("SAES") == []


def test_the_map_is_rebuilt_when_the_corpus_changes():
    client = TestClient(app)
    upload(client, [PARENTHETICAL])
    assert "NDFT" in acronyms.harvest()
    upload(client, [GLOSSARY], name="glossary.pdf")
    both = acronyms.harvest()
    assert "NDFT" in both and "CPS" in both


# ------------------------------------------------------- through the gate


def test_a_question_using_an_acronym_the_document_only_spells_out_answers():
    """The case that started this. FULL_TERM_ONLY never writes NDFT."""
    client = TestClient(app)
    upload(client, [PARENTHETICAL, FULL_TERM_ONLY])
    result = answer_mod.answer("what happens to the NDFT where a repair is required")
    assert result["answer_type"] == "extract"
    assert "NDFT" not in result["lexical"]["absent_from_corpus"]


def test_a_question_using_the_full_term_matches_a_chunk_that_only_writes_the_acronym():
    """The other direction, which is the half that is easy to forget."""
    client = TestClient(app)
    upload(client, [PARENTHETICAL, ACRONYM_ONLY])
    verdict = lexical.assess(
        "what is the nominal dry film thickness for the submerged zone",
        "The NDFT for the submerged zone shall not be less than 350 um.",
    )
    assert verdict["ok"] is True
    assert "nominal" not in verdict["absent_from_corpus"]


def test_a_genuinely_absent_term_still_refuses():
    """The gate must not have been widened into uselessness."""
    client = TestClient(app)
    upload(client, [PARENTHETICAL, GLOSSARY, ACRONYM_ONLY])
    result = answer_mod.answer("what cladding thickness is required for Inconel 625")
    assert result["answer_type"] == "insufficient_evidence"
    assert "Inconel" in result["lexical"]["absent_from_corpus"]


def test_an_absent_acronym_gets_a_useful_refusal_not_a_dead_end():
    client = TestClient(app)
    upload(client, [PARENTHETICAL, GLOSSARY])
    result = answer_mod.answer("what does SAES require for shop priming")
    assert result["answer_type"] == "insufficient_evidence"
    assert "If it is an abbreviation, try the full term" in result["reason"]


def test_an_absent_ordinary_word_does_not_get_the_abbreviation_hint():
    """The hint has to mean something. Offered on every refusal it is noise."""
    client = TestClient(app)
    upload(client, [PARENTHETICAL, GLOSSARY])
    result = answer_mod.answer("what is the Inconel cladding requirement")
    assert result["answer_type"] == "insufficient_evidence"
    assert "abbreviation" not in (result["reason"] or "")


def test_the_expansion_map_never_invents_an_equivalence():
    """A wrong expansion would be worse than none: it would make a question
    about one thing match a passage about another, with a citation."""
    client = TestClient(app)
    upload(client, [PARENTHETICAL, GLOSSARY, INVERSE])
    for acronym, expansions in acronyms.harvest().items():
        for expansion in expansions:
            assert acronyms.initials_match(acronym, expansion), (acronym, expansion)
