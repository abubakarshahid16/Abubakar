"""A facet must name a SUBJECT, not a coincidence of vocabulary.

MEASURED, on the live question "do your deep analysis find all structural
models from all documents". The gap analysis came back with ten facets:

    analysis, analysis (%), analysis documents, documents (%), models,
    models (%), models structural, section 5, section 7, structural

Nine of them are noise from one cause: the facet key was literally
(question terms ∩ claim terms), so a claim saying {documents}, a claim saying
{documents, drawing} and a claim saying {drawing} became three facets of one
subject - and "(%)" got into a facet NAME because a percentage, which is an
attribute of a claim, was allowed to identify one.

Every test here fails against the pre-fix `claims.py`. That is the point: the
suite has a history of tests that pass either way (one read only the "200" key
so 201 routes went unguarded; another skipped itself), and a test that would
still pass with the fix deleted is not a test.
"""

from __future__ import annotations

import re

import pytest

from app import claims, db, keyword
from app.config import settings
from app.claims import (
    POSSIBLE_CONFLICT_NOTE,
    cluster,
    extract_claims,
    extract_measurements,
    question_terms,
    to_api,
)

VALID_LABELS = {"agreement", "addition", "possible_conflict", "unresolved"}


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    """`claims` reaches the database through `keyword` and `lexical`.

    COPIED FROM test_claims.py DELIBERATELY, and for the reason its own
    docstring gives: without it these tests pass on a development machine -
    which has a 71 MB corpus at backend/data/nabaa.sqlite - and fail anywhere
    else with `no such table: chunks`. This file was written without it and did
    exactly that: 8 passes on the dev box, 8 failures in a clean container.
    A test that needs a database it did not create is testing the machine.
    """
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def _evidence(evidence_id: str, text: str, filename: str = "a.pdf", page: int = 1) -> dict:
    return {
        "evidence_id": evidence_id,
        "filename": filename,
        "page_start": page,
        "section": None,
        "exact_span": text,
    }


def _clusters(question: str, evidence: list[dict]):
    return cluster(extract_claims(evidence), question_terms(question))


# --------------------------------------------- one subject, two levels of detail


def test_documents_and_drawing_documents_are_one_facet_not_two():
    """{documents} and {documents, drawing} are the same subject.

    A claim that says "the drawing documents" is speaking about documents in
    more detail, not about a second thing. Pre-fix this produced two facets,
    each with one row and each reading "only one document speaks to this
    facet" - the report saying twice that it has nothing to compare, about a
    pair of statements that do compare.
    """
    out = _clusters(
        "which drawing documents must be submitted",
        [
            _evidence("e1", "All documents shall be submitted for review per ISO 19650."),
            _evidence("e2", "The drawing documents shall be submitted per ISO 19650.", "b.pdf"),
        ],
    )
    assert len(out) == 1, f"one subject became {len(out)} facets: {[c.facet for c in out]}"
    (facet,) = out
    assert {r.evidence_id for r in facet.rows} == {"e1", "e2"}
    # And the name is a phrase the claims use, not the query's words in
    # alphabetical order ("documents drawing submitted").
    assert facet.facet == "documents", facet.facet
    assert facet.label in VALID_LABELS


def test_a_narrower_facet_is_not_absorbed_by_an_unrelated_head_noun():
    """Guard the guard: the merge must not swallow everything it touches.

    "drawing documents" is a kind of documents (head noun: documents), so it
    merges. "document drawings" is a kind of DRAWINGS, so a facet about
    documents must not absorb it - otherwise "merge on subset" degenerates
    into "merge on any shared word", which is the original defect again.
    """
    out = _clusters(
        "which drawings and documents must be submitted",
        [
            _evidence("e1", "The register lists the drawings per ISO 19650."),
            _evidence("e2", "All documents shall be submitted per ISO 19650.", "b.pdf"),
        ],
    )
    facets = sorted(c.facet for c in out)
    assert len(out) == 2, f"two different subjects were merged into {facets}"
    assert facets == ["documents", "drawings"], facets


# --------------------------------------------- a unit is not a subject


def test_no_facet_key_or_label_carries_a_unit_symbol_or_a_bare_numeral():
    """"documents (%)" and "7.1 coating solids" are not subjects.

    A percentage is dimensionless - what it is a percentage OF is decided by
    the words around it - and a clause number is an address, not a thing that
    can be agreed with. Pre-fix, both got into the facet key: the percentage
    split "coating solids" into "coating solids" and "coating solids (%)",
    and the clause number prefixed the name.
    """
    evidence = [
        _evidence("e1", "Section 7.1 states the coating solids shall be 60% by volume."),
        _evidence("e2", "The coating solids shall be measured per ISO 3233.", "b.pdf"),
    ]
    out = _clusters("does section 7.1 require coating solids", evidence)

    assert len(out) == 1, f"a percentage split one subject: {[c.facet for c in out]}"
    (facet,) = out
    assert facet.facet == "coating solids", facet.facet
    for c in out:
        assert "%" not in c.facet and "(%)" not in c.facet
        assert not re.search(r"(?<![A-Za-z0-9.])\d", c.facet), f"a number names nothing: {c.facet}"
        for token in c.key:
            if token.startswith(("dim:", "designator:")):
                continue
            assert any(ch.isalpha() for ch in token), f"unit/number token in key: {token!r}"
            assert token != "%" and token != "(%)"

    # THE HALF THAT MATTERS. None of the above may be bought by throwing the
    # percentage away: 60% is a real requirement and must still be extracted,
    # still carried on the row, and still comparable.
    assert [m.raw_value for m in extract_measurements(evidence[0]["exact_span"])] == ["60"]
    values = {row["raw_value"] for row in to_api(out)[0]["rows"]}
    assert "60" in values, f"the percentage was lost from the rows: {values}"


# --------------------------------------------- recall


def test_a_real_disagreement_survives_and_is_found_by_the_merge():
    """125 µm against 280 µm is a disagreement whatever else the sentences say.

    Pre-fix these were two single-row facets ({coating, thickness} and
    {coating, thickness, primer}), each labelled "addition", and the
    contradiction was never reported at all. Merging is what finds it.
    """
    out = _clusters(
        "what primer coating thickness is required",
        [
            _evidence("e1", "The coating thickness shall be 125 um."),
            _evidence("e2", "The primer coating thickness shall be 280 um.", "b.pdf"),
        ],
    )
    assert len(out) == 1, [c.facet for c in out]
    (facet,) = out
    assert facet.label == "possible_conflict", f"{facet.facet}: {facet.label}"
    assert facet.note == POSSIBLE_CONFLICT_NOTE
    assert {r.evidence_id for r in facet.rows} == {"e1", "e2"}
    assert {r.filename for r in facet.rows} == {"a.pdf", "b.pdf"}
    # "primer" is one of the question's words, so pre-fix e2 keyed
    # {coating, primer, thickness} and e1 keyed {coating, thickness}: two
    # facets, two "addition" labels, no conflict reported anywhere.
    assert facet.facet == "coating thickness (µm)", facet.facet


def test_a_conflict_is_never_merged_away_into_a_broader_facet():
    """THE RECALL GUARD. Merging may add evidence, never dissolve a finding.

    {mdft} carries a hard 280 against a hard 250 - a possible_conflict. The
    broader {coating, mdft} facet is headed by "mdft", so the subset rule
    would fold the conflict into it - and that facet's rows name system 1 and
    system 9, which makes the merged cluster "unresolved" and the
    disagreement disappears from the report. It must not.
    """
    out = _clusters(
        "what mdft applies to the coating",
        [
            _evidence("e1", "MDFT 280 um."),
            _evidence("e2", "MDFT 250 um.", "b.pdf"),
            _evidence("e3", "Coating MDFT for system no. 1 is 300 um.", "c.pdf"),
            _evidence("e4", "Coating MDFT for system no. 9 is 400 um.", "d.pdf"),
        ],
    )
    conflicts = [c for c in out if c.label == "possible_conflict"]
    assert conflicts, f"the disagreement was merged away: {[(c.facet, c.label) for c in out]}"
    assert {r.evidence_id for r in conflicts[0].rows} == {"e1", "e2"}
    assert conflicts[0].note == POSSIBLE_CONFLICT_NOTE
    # The designator facet is still reported, and still says why it cannot be
    # compared - the status vocabulary is unchanged by any of this.
    assert {c.label for c in out} <= VALID_LABELS


# --------------------------------------------- a facet needs claims


def test_a_facet_with_no_claims_on_either_side_is_not_emitted():
    """A question word turning up in a sentence is not a finding.

    "The 95% figure in 7.1 applies." shares exactly one token with the
    question "what does 7.1 require", and that token is a clause number. Pre-
    fix it produced a facet named "7.1" holding one row; there is nothing to
    agree or disagree with, and the row is not about a subject at all.
    """
    out = _clusters("what does 7.1 require", [_evidence("e1", "The 95% figure in 7.1 applies.")])
    assert out == [], f"a facet was invented from a clause number: {[c.facet for c in out]}"

    # Nor from a shared word that names nothing: no claim, no facet.
    text = "Pressure shall be 280 um."
    assert _clusters("what adhesion is required",
                     [_evidence("e1", text), _evidence("e2", text, "b.pdf")]) == []


def test_every_emitted_facet_has_rows_and_a_name():
    """The invariant behind the three cases above, asserted over all of them."""
    corpora = [
        ("which drawing documents must be submitted",
         [_evidence("e1", "All documents shall be submitted for review per ISO 19650."),
          _evidence("e2", "The drawing documents shall be submitted per ISO 19650.", "b.pdf")]),
        ("does section 7.1 require coating solids",
         [_evidence("e1", "Section 7.1 states the coating solids shall be 60% by volume."),
          _evidence("e2", "The coating solids shall be measured per ISO 3233.", "b.pdf")]),
        ("do your deep analysis find all structural models from all documents",
         [_evidence("e1", "The structural models shall be submitted as 100% Design Documents."),
          _evidence("e2", "Structural models for the drawing documents are listed in section 5.", "b.pdf"),
          _evidence("e3", "All documents per ISO 19650 shall be provided.", "c.pdf"),
          _evidence("e4", "The analysis in section 7 covers 25% of the structural models.", "d.pdf")]),
    ]
    for question, evidence in corpora:
        out = _clusters(question, evidence)
        names = [c.facet for c in out]
        assert len(names) == len(set(names)), f"two facets with one name: {names}"
        for c in out:
            assert c.rows, f"{c.facet!r} was emitted with no claims"
            assert c.facet and c.facet != "unnamed"
            assert "%" not in c.facet
            assert c.label in VALID_LABELS


@pytest.mark.parametrize("sentence,value", [
    ("Energy use shall be at least 30% below ASHRAE 90.1.", "30"),
    ("The coating shall cover 95% of the surface.", "95"),
    ("Humidity shall not exceed 85% during application.", "85"),
])
def test_keeping_percent_out_of_facet_names_did_not_suppress_percentages(sentence, value):
    """A previous attempt at the "(%)" noise widened the phase-percent rule to
    "any capitalised word" and silently suppressed every real percentage -
    re.IGNORECASE makes [A-Z][a-z]+ match lowercase. The extractor is
    untouched here, and this says so out loud."""
    assert [m.raw_value for m in extract_measurements(sentence)] == [value]


def test_the_live_ten_facet_question_collapses_to_its_subjects():
    """The observed defect, end to end.

    Ten facet names for two subjects. After the fix the claims about
    structural models sit in ONE facet whose name a human recognises, and
    nothing is named after a percent sign, a section number or a pair of
    query words in alphabetical order.
    """
    out = _clusters(
        "do your deep analysis find all structural models from all documents",
        [
            _evidence("e1", "The structural models shall be submitted as 100% Design Documents."),
            _evidence("e2", "Structural models for the drawing documents are listed in section 5.", "b.pdf"),
            _evidence("e3", "All documents per ISO 19650 shall be provided.", "c.pdf"),
            _evidence("e4", "The analysis in section 7 covers 25% of the structural models.", "d.pdf"),
            _evidence("e5", "Deep analysis of the structural models is required in section 7.", "e.pdf"),
        ],
    )
    names = sorted(c.facet for c in out)
    assert len(names) <= 3, f"still a bag of query words: {names}"
    assert "structural models" in names, names
    for bad in ("analysis (%)", "documents (%)", "models (%)", "models structural",
                "analysis documents", "section 5", "section 7"):
        assert bad not in names, f"{bad!r} is still being emitted"
