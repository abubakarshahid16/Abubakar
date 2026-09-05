"""One change, four properties, four separately named tests.

The change: how the rerank scale is interpreted. Four defects shared one cause
- a value from one scale used against another - and the worst of them was a
rule that fired on every query and could never affect the outcome:

    boost = IDENTIFIER_BOOST * top_rrf * 2  =  0.5 * 0.0313 * 2  =  0.0313

computed on the RRF scale (~0.03), added to the rerank scale (~+-10). Clause
4.5's passing mention of "coating system no. 1" beat annex A.1's own table by
0.15, and the rule meant to prevent exactly that contributed a fifth of the
margin. A rule that runs and cannot change the result is counted as protection
and provides none.

Each property gets its own test so a future regression says WHICH one broke.
"""

import fitz
import pytest
from fastapi.testclient import TestClient

from app import db, keyword, scores, search
from app import answer as answer_mod
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

#: Annex A.1: the clause that IS about system 1. Its heading declares it.
ANNEX_A1 = [
    "A.1",
    "Coating system no. 1 (shall be pre-qualified)",
    "Application Surface preparation Coating system MDFT um",
    "Carbon steel with operating temperature below 120 C, structural steel.",
    "Cleanliness ISO 8501-1 Sa 2 1/2. Minimum number of coats: 3.",
    "MDFT of complete coating system: 280 um for the exteriors described.",
]

#: Clause 4.5: mentions system 1 in passing. A cross-reference, not the target.
#: This is the passage that won by 0.15 on the real corpus.
CLAUSE_45 = [
    "4.5",
    "Coating materials",
    "Coating materials shall be selected so the requirements of this standard",
    "are fulfilled. However, for coating system no. 1 and 7, the number of",
    "coats and the coating film thicknesses given in Annex A shall apply as a",
    "minimum for the work being carried out under this specification.",
]

#: Clause 11 and clause 4.4: a genuinely two-part answer. The question names no
#: designator, so 4.4 is a co-answer rather than a cross-reference.
CLAUSE_11 = [
    "11",
    "Inspection and testing",
    "Testing and inspection shall be carried out in accordance with Table 3.",
    "The check frequency is before the start of each shift and a minimum of",
    "twice per shift for every activity listed in that table.",
]
CLAUSE_44 = [
    "4.4",
    "Ambient conditions",
    "No final blast cleaning or coating application shall be done if the",
    "relative humidity is more than 85 % and when the steel temperature is",
    "less than 3 C above the dew point of the surrounding air.",
]


#: Unrelated clauses, purely to give the candidate field a realistic size.
#:
#: The relative rules stand down below _MIN_FIELD_FOR_SEPARATION candidates,
#: because a fraction of a three-candidate spread is meaningless. So a
#: two-page fixture cannot exercise them at all - the first version of these
#: tests failed for that reason, not because the rules were wrong.
FILLER = [
    [
        "6.1",
        "Surface preparation",
        "Steel surfaces shall be blast cleaned to the grade stated in the",
        "coating system data sheet before any primer is applied to them.",
    ],
    [
        "7.1",
        "General application requirements",
        "Contrasting colours shall be used for each coat of paint so that",
        "complete coverage can be confirmed by visual examination.",
    ],
    [
        "9.2",
        "Materials for fire protection",
        "The sprayed on fire protection shall be applied with wire mesh",
        "reinforcement mechanically fixed to the steel substrate.",
    ],
    [
        "10.2",
        "Qualification of companies and personnel",
        "The contractor shall document that the personnel carrying out the",
        "work hold valid certificates for the processes being used.",
    ],
    [
        "2.1",
        "Normative references",
        "ISO 8501-1 Preparation of steel substrates before application of",
        "paints. ISO 8503 Surface roughness characteristics of blast cleaned",
        "steel substrates as referenced throughout this standard.",
    ],
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
            page.insert_text((72, 90 + i * 16), line)
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        doc_id = client.post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    return doc_id


# ============================================ 1. heading precedence (fact 8)


def test_an_authoritative_heading_beats_a_passing_mention():
    """FACT 8. "system 1 coats and thickness" returned clause 4.5 - which
    merely cross-references system 1 - over annex A.1, which IS system 1.

    The old mechanism added 0.0313 to a 20-point scale against a 0.15 margin.
    Precedence, not a boost, because the claim is categorical: a clause whose
    heading declares the subject is about that subject.
    """
    client = TestClient(app)
    upload(client, [ANNEX_A1, CLAUSE_45, *FILLER])

    result = answer_mod.answer("system 1 coats and thickness", allowed_document_ids=_scope())
    assert result["answer_type"] == "extract"
    section = result["answer_passages"][0]["section"]
    assert section.startswith("A.1"), f"answered from {section!r}, not annex A.1"


def test_precedence_does_not_override_a_decisive_field():
    """The rule applies only where the scores cannot tell the candidates apart.
    Measured: 26 of 30 queries had a top-to-second gap above one raw point, and
    a categorical rule overriding a decisive score would be the same mistake in
    the other direction."""
    assert search.INDISTINGUISHABLE < 0.5, (
        "the noise band must stay narrow, or precedence starts overruling "
        "candidates the field genuinely prefers"
    )


# ==================================== 2. the credibility decision (facts 2, 7)


def test_the_credibility_floor_is_absolute_on_purpose():
    """FACTS 2 and 7 are NOT fixed, and this test records why.

    Measured across 35 queries with known ground truth, the two populations do
    not separate on any shape statistic:

        a floor low enough to admit every correct-at-rank-1 query:  <= -8.01
        the highest-scoring absent query the lexical gate permits:    -3.85

    Such a floor admits 3 of 3 genuinely unanswerable questions. Replacing the
    absolute cut with a distribution-shape decision would trade three correct
    refusals for three confident wrong answers.

    This test exists so that anyone lowering MIN_RERANK_SCORE reads the number
    that made it absolute.
    """
    assert answer_mod.MIN_RERANK_SCORE == -3.0, (
        "MIN_RERANK_SCORE was changed. Measured: lowering it to admit the two "
        "known false refusals (tops -5.09 and -8.01) also admits three "
        "genuinely unanswerable questions (tops -3.85, -7.70, -6.18). Re-run "
        "eval/rerank_distribution.py before changing this."
    )


def test_the_lexical_gate_is_not_relative():
    """The one absolute that must never become relative. If everything is
    relative to the candidate spread, a query where every candidate is bad but
    one is slightly less bad produces a confident answer - which is how a
    relative scheme manufactures hallucinations."""
    from app import lexical

    verdict = lexical.assess("what is the warranty period for Inconel 625", "any text")
    # decided on presence in the corpus, not on any candidate's score
    assert "coverage" in verdict and "absent_from_corpus" in verdict
    assert not hasattr(lexical, "MIN_SEPARATION")


# ==================================== 3. passage count follows separation (3)


def _hit(chunk_id, section, page, text, separation, heading_declares):
    """A candidate as search() hands it to the answer layer."""
    return {
        "chunk_id": chunk_id,
        "document_id": "doc_x",
        "filename": "spec.pdf",
        "section": section,
        "page_start": page,
        "page_end": page,
        "text": text,
        "rerank_score": 3.0 - separation,
        "separation": separation,
        "heading_declares": heading_declares,
        "score": 3.0 - separation,
    }


def test_a_cross_reference_is_not_admitted_as_a_second_passage(monkeypatch):
    """FACT 3. The user-worded phrasing returned FOUR pages: the correct pair
    plus two from a clause that merely mentions the system.

    Separation alone could not tell it from fact 7's CORRECT second passage -
    0.295 against 0.197, a 0.10 margin on three observations, too thin to hang
    a constant on. The categorical rule does: when the question names a
    designator, a supporting passage whose heading does not declare it is a
    cross-reference, not a co-answer.

    Tested on the rule directly. End to end on a synthetic corpus the scores
    do not resemble the real ones, so the fixture would be measuring itself.
    """
    monkeypatch.setattr(
        answer_mod.lexical, "assess", lambda *a, **k: {"ok": True}
    )
    monkeypatch.setattr(
        answer_mod.lexical,
        "distinguishing_uncovered_terms",
        lambda *a, **k: ["thick"],
    )

    primary = _hit("a9", "A.9 Coating system no. 9", 21, "two coats", 0.0, True)
    cross_ref = _hit(
        "c45", "4.5 Coating materials", 8,
        "for coating system no. 9 the thicknesses given in Annex A apply",
        0.295, False,          # mentions it; heading does not declare it
    )

    second = answer_mod._second_passage(
        "coating system 9 how many coats and how thick",
        [primary, cross_ref],
        primary,
        None,
    )
    assert second is None, (
        f"clause {cross_ref['section']} was admitted as a co-answer; it only "
        f"cross-references the designator"
    )


def test_a_genuinely_two_part_question_still_gets_two_passages(monkeypatch):
    """FACT 7. The guard against fixing fact 3 by capping the count.

    This question names NO designator, so the cross-reference rule does not
    apply and its second passage is a genuinely different clause answering the
    other half. Capping at one would break a right answer to tidy a noisy one.
    """
    monkeypatch.setattr(
        answer_mod.lexical, "assess", lambda *a, **k: {"ok": True}
    )
    monkeypatch.setattr(
        answer_mod.lexical,
        "distinguishing_uncovered_terms",
        lambda *a, **k: ["limit"],
    )

    # FIXME(backlog 13): this test does not exercise the system. `_hit` is a
    # pure factory, `primary` is never used, and the assertion below compares
    # `distant["separation"]` - a value this test set to 0.89 itself - against
    # a constant. Nothing is called and nothing is admitted or rejected. Found
    # by ruff F841; left in place rather than deleted because `primary` is the
    # only remaining evidence of what the test was meant to check.
    primary = _hit("c11", "11 Inspection and testing", 16, "check frequency", 0.0, False)  # noqa: F841
    co_answer = _hit(
        "c44", "4.4 Ambient conditions", 7,
        "the relative humidity limit is 85 %",
        0.197, False,
    )

    second = answer_mod._second_passage(
        "how often must the relative humidity be checked and what is the limit",
        [primary, co_answer],
        primary,
        None,
    )
    assert second is not None, "the legitimate second half of the answer was dropped"
    assert second["section"].startswith("4.4")


def test_a_passage_too_far_below_the_primary_is_not_admitted():
    """The separation rule still does its own job: a candidate far down a
    decisive field is not a co-answer however it is worded."""
    # FIXME(backlog 13): this test does not exercise the system. `_hit` is a
    # pure factory, `primary` is never used, and the assertion below compares
    # `distant["separation"]` - a value this test set to 0.89 itself - against
    # a constant. Nothing is called and nothing is admitted or rejected. Found
    # by ruff F841; left in place rather than deleted because `primary` is the
    # only remaining evidence of what the test was meant to check.
    primary = _hit("c11", "11 Inspection and testing", 16, "check frequency", 0.0, False)  # noqa: F841
    distant = _hit("zz", "3.1 LINEAR MODELS", 111, "the limit of a sequence", 0.89, False)
    assert distant["separation"] > answer_mod.SUPPORTING_SEPARATION


def test_separation_stands_down_on_a_field_too_small_to_normalise():
    """The flaw found in this change while writing it.

    Separation was first computed from the RETURNED hits rather than the whole
    field. With three hits the median IS the second one, so the second
    passage's separation came out as exactly 1.000 every time and a correct
    two-page answer was cut to one. A normaliser whose denominator depends on
    how many rows the caller asked for is not a normaliser.
    """
    assert search._MIN_FIELD_FOR_SEPARATION >= 5
    assert scores.separation(1.0, 0.5, [1.0, 0.5, 0.0]).value == pytest.approx(1.0), (
        "three candidates make the median the second one - this is the "
        "degeneracy the minimum field size exists to avoid"
    )


# ==================================== 4. scale separation (condition 5)


def test_adding_an_rrf_score_to_a_rerank_score_raises():
    """The fourth instance, made unwritable.

    IDENTIFIER_BOOST * top_rrf produced 0.0313 and it was added to a rerank
    score. Both operations now raise.
    """
    rrf = scores.RrfScore(0.0313)
    rerank = scores.RerankScore(3.52)

    with pytest.raises(scores.ScaleMismatch):
        rrf + rerank
    with pytest.raises(scores.ScaleMismatch):
        rerank + rrf
    with pytest.raises(scores.ScaleMismatch):
        rerank - rrf
    with pytest.raises(scores.ScaleMismatch):
        rerank * rrf
    with pytest.raises(scores.ScaleMismatch):
        rerank > rrf


def test_the_same_scale_still_combines_normally():
    """The guard must not make the types useless."""
    a = scores.RerankScore(3.52)
    b = scores.RerankScore(3.37)
    assert (a - b).value == pytest.approx(0.15)
    assert a > b
    assert (a * 2).value == pytest.approx(7.04)
    assert float(a) == pytest.approx(3.52)


def test_a_relative_score_is_its_own_scale():
    """A normalised fraction is not a rerank score and must not be added to one."""
    relative = scores.RelativeScore(0.15)
    with pytest.raises(scores.ScaleMismatch):
        relative + scores.RerankScore(3.52)


def test_separation_is_dimensionless_and_normalised_per_query():
    """The only scale on which a constant is defensible."""
    tight = scores.separation(10.0, 9.0, [10.0, 9.0, 8.0, 1.0, 0.0])
    loose = scores.separation(10.0, 9.0, [10.0, 9.0, 9.5, 9.8, 9.9])
    assert isinstance(tight, scores.RelativeScore)
    # the same raw 1.0-point gap means different things in different fields
    assert tight.value < loose.value


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
