"""Measured accuracy defects in the ANALYSIS retrieval path, each with a test.

Three failures were measured against a page-verified gold set over the client's
thirteen-document corpus (eval/gold_analysis.json, eval/score_analysis_gold.py).
That corpus is not in the repository, so every test here builds its own fixture
documents with the same SHAPE as the measured ones: a verbose specification, a
second specification that answers the question on one late page, and an
off-topic textbook that wins on bare words.

FAILURE 1 - a maths textbook took top-1 on the words "design", "model" and
  "scale" for structural-engineering questions, and a live claim table cited
  "7.42 Which of the following models do you think would produce very accurate
  results?" as engineering evidence. Where the question NAMES the documents the
  textbook is not competing evidence; it is noise the reader excluded.

FAILURE 2 - "compare design submittal percentages in doc13.pdf and doc16.pdf"
  at limit=24 gave doc16 EIGHTEEN of the 24 slots (pages 2, 19, 21, 24, 29, 32,
  35, 37) and doc16 p.18, which carries the answer, was not among them.

FAILURE 3 - a FALSE POSSIBLE GAP caused by failure 2. doc13 p.125 says "16.2
  Concept/early Preliminary (35%) Design Submittal"; doc16 p.18 says "a draft
  submission (usually at least a 50% design submission)". Both clauses are in
  the corpus. Retrieval returned only doc13's, so gap analysis truthfully
  reported that one document alone spoke to the facet - inventing a compliance
  gap that does not exist. The gap logic was honest; retrieval starved it.

WHAT IS DELIBERATELY NOT STUBBED. The scope tests run through the REAL
`search()` with a spy on its arguments, because the claim being made is about
the argument the analysis path passes: naming a document in a question must
never widen the set of documents searched. A stub returning a chosen list of
hits would assert nothing about that.
"""

from __future__ import annotations

import pytest

from app import access, analysis, db, keyword
from app.config import settings

NOW = "2026-09-07T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "u")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    yield
    db.reset_connection()


# --------------------------------------------------------- the fixture corpus


#: doc13 p.125, in the shape the gold set records it.
D13_PERCENT = ("16.2 Concept/early Preliminary (35%) Design Submittal shall "
               "include the site plan, outline specifications and the "
               "structural framing concept for the owner to review.")

#: doc16 p.18. The clause the product could not reach. Its only percentage
#: marker is "50%" - no form of the word "percentage" appears in it, which is
#: exactly why literal-word retrieval never ranked it for a question about
#: percentages.
D16_PERCENT = ("The design professional shall provide a draft submission "
               "(usually at least a 50% design submission) to the owner for "
               "coordination review before the work proceeds.")

#: The eight verbose doc16 pages that took the candidate set. Heavy on the
#: question's own words and carrying no answer at all.
#:
#: Each is a DIFFERENT sentence on purpose. `search.deduplicate` evicts chunks
#: sharing 0.85 of their tokens, so eight paraphrases of one sentence would
#: collapse to one and the verbose document this fixture exists to reproduce
#: would not be verbose. They carry no digits, so nothing here competes with
#: the percent-bearing clauses on a bare number.
D16_FILLER = [
    (2, "Design submittal drawings shall be issued at each stage of the work "
        "under the general conditions of the agreement."),
    (19, "The design submittal package includes structural framing plans, "
         "sections and typical connection details."),
    (21, "Mechanical design submittal documents shall show equipment "
         "schedules, duct layouts and control diagrams."),
    (24, "Electrical design submittal sheets shall carry panel schedules, "
         "single line diagrams and fixture types."),
    (29, "Plumbing design submittal drawings shall indicate fixture units, "
         "riser diagrams and pipe materials."),
    (32, "Landscape design submittal sheets shall present planting schedules, "
         "irrigation zones and hardscape finishes."),
    (35, "The civil design submittal shall present grading, drainage, utility "
         "routing and pavement sections."),
    (37, "Architectural design submittal sheets shall present floor plans, "
         "elevations, wall types and door schedules."),
]

#: FORTY-FOUR more verbose doc16 pages, used only by `crowded_corpus`.
#:
#: MEASURED on the real corpus, within doc16 ALONE: the clause "a draft
#: submission (usually at least a 50% design submission)" on p.18 is bm25 rank
#: 75 of 94 matches for the question and rank 44 of 94 with the percent terms
#: appended. `settings.search_candidates` is 30, so the clause was never
#: RETRIEVED - it does not even appear in `shortlist_excluded`.
#:
#: EVERY FILLER CARRIES "Page 50 of 100", because the real doc16 carries a
#: "Page 15 of 46" running head on every page. That detail is the whole reason
#: the clause is buried: it makes "50" and "100" COMMON, so the one rare thing
#: about the clause is gone and bm25 ranks it below every page whose words
#: match the question better. A fixture where "50" appears only in the clause
#: gives it a high IDF and ranks it FIRST - measured here: the first version
#: of this fixture did exactly that, and three mutations of the fix survived
#: against it.
_TRADES = ("site survey", "geotechnical", "structural steel", "concrete formwork",
           "masonry veneer", "roofing membrane", "curtain wall",
           "interior partition", "acoustic ceiling", "fire protection",
           "security cabling")
_ARTEFACTS = ("setting-out dimensions", "material grades", "connection details",
              "inspection holds")
_VERBS = ("accompany", "precede", "follow", "complete")
_NOUNS = ("civil", "architectural", "mechanical", "electrical", "structural",
          "landscape", "interior", "acoustic", "hydraulic", "electronic",
          "topographic")
D16_MORE_FILLER = [
    (100 + t * 4 + a,
     f"Page 50 of 100 {trade} {artefact} {_VERBS[a]} the {_NOUNS[t]} design "
     f"submittal for review.")
    for t, trade in enumerate(_TRADES)
    for a, artefact in enumerate(_ARTEFACTS)
]

#: EIGHTEEN doc16 pages that are not paraphrases of each other.
#:
#: The forty-four above are near-paraphrases, and `search.deduplicate` evicts
#: chunks sharing 0.85 of their tokens - measured on the first version of this
#: fixture, 40 of doc16's 53 candidates were evicted as near-duplicates, the
#: surviving pool fell to 13, and the `rerank_candidates` shortlist cut (16)
#: therefore never bit. The clause then reached the reranker for free and two
#: mutations of the fix survived. These carry distinct vocabulary so they
#: SURVIVE dedup and genuinely fill the shortlist, which is what the real
#: doc16 does with its own forty-six pages of distinct prose.
D16_DISTINCT = [
    (201, "Page 50 of 100 Clash detection reports shall accompany the design "
          "submittal with tolerances agreed at the kickoff meeting."),
    (202, "Page 50 of 100 Federated models in the design submittal shall use "
          "shared coordinates published by the survey control authority."),
    (203, "Page 50 of 100 Room data sheets in each design submittal shall "
          "enumerate occupancy, ventilation rates and acoustic separation."),
    (204, "Page 50 of 100 The design submittal shall name the software release "
          "and export format used for every discipline file."),
    (205, "Page 50 of 100 Object naming conventions for the design submittal "
          "follow the employer information requirements appendix."),
    (206, "Page 50 of 100 Quantity take-off tables accompanying the design "
          "submittal shall reconcile against the priced bill."),
    (207, "Page 50 of 100 Point cloud registration for the design submittal "
          "shall report deviation statistics per scan station."),
    (208, "Page 50 of 100 Wayfinding signage schedules in the design submittal "
          "shall cross-reference the accessibility narrative."),
    (209, "Page 50 of 100 Commissioning witness points in the design submittal "
          "shall identify responsible trades and hold durations."),
    (210, "Page 50 of 100 Roof drainage calculations in the design submittal "
          "shall state rainfall intensity and gutter capacity."),
    (211, "Page 50 of 100 Blast and progressive collapse notes in the design "
          "submittal shall reference the threat assessment memorandum."),
    (212, "Page 50 of 100 Envelope thermal bridging in the design submittal "
          "shall be quantified with linear transmittance values."),
    (213, "Page 50 of 100 Lightning protection zoning in the design submittal "
          "shall show mesh spacing and down-conductor routes."),
    (214, "Page 50 of 100 Vertical transportation traffic analysis in the "
          "design submittal shall state waiting interval assumptions."),
    (215, "Page 50 of 100 Kitchen ventilation make-up air in the design "
          "submittal shall balance against the grease extract volume."),
    (216, "Page 50 of 100 Medical gas manifold rooms in the design submittal "
          "shall show cylinder storage and alarm panel positions."),
    (217, "Page 50 of 100 Landscape irrigation zoning in the design submittal "
          "shall state emitter flow and controller programming."),
    (218, "Page 50 of 100 Temporary works interfaces in the design submittal "
          "shall identify crane positions and hoarding lines."),
]

#: doc13's other submittal percentages. The real doc13 carries dozens, which is
#: why a single recall call over both documents came back 15 doc13 passages to
#: 1 doc16 passage: the recall pass gets eaten exactly as the primary one does.
D13_OTHER_PERCENTS = [
    (41, "The ninety percent (90%) Design Submittal shall be complete except "
         "for final checking and back-checking of the documents."),
    (50, "A sixty percent (60%) Design Submittal is required for the review "
         "conference described in this paragraph."),
    (52, "The one hundred percent (100%) Design Submittal shall incorporate "
         "all back-check comments from the previous submittal."),
    (77, "Cost estimates accompanying each (35%) or (60%) Design Submittal "
         "shall follow the work breakdown structure."),
    (91, "The corrected final (100%) Design Submittal shall be furnished "
         "before the contract completion date."),
]

#: The off-topic textbook that took top-1 on "design", "model" and "scale".
BOOK2 = [
    (410, "7.42 Which of the following models do you think would produce very "
          "accurate results? Consider the design of the model and the scale "
          "of the design problem before you model the differential equation."),
    (411, "7.43 A model at any scale may be used for a design study. Sketch "
          "the design curve and model the scale factor for each design case."),
    (412, "7.44 Model the design of the piping example at the scale given and "
          "compare your design model against the tabulated design values."),
]


def _document(doc_id: str, filename: str) -> None:
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO documents (id, filename, sha256, size_bytes,
                    stored_path, page_count, status, uploaded_at)
               VALUES (?, ?, ?, 1, ?, 500, 'ready', ?)""",
            (doc_id, filename, f"sha-{doc_id}", f"/tmp/{filename}", NOW),
        )


def _chunks(doc_id: str, filename: str, pages_text) -> None:
    with db.connect() as conn:
        for ordinal, (page, text) in enumerate(pages_text):
            conn.execute(
                """INSERT INTO chunks (id, document_id, filename, ordinal,
                        page_start, page_end, section, kind, text, token_count,
                        content_hash, retrievable)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, 'prose', ?, ?, ?, 1)""",
                (f"{doc_id}_c{ordinal}", doc_id, filename, ordinal, page, page,
                 text, len(text.split()), f"h_{doc_id}_{ordinal}"),
            )
    keyword.index_document(doc_id)


def corpus() -> None:
    """doc13, doc16 and the textbook, indexed for keyword retrieval."""
    _document("d13", "doc13.pdf")
    _chunks("d13", "doc13.pdf", [(125, D13_PERCENT)])
    _document("d16", "doc16.pdf")
    _chunks("d16", "doc16.pdf", [(18, D16_PERCENT), *D16_FILLER])
    _document("b2", "book2-Differential-Equations.pdf")
    _chunks("b2", "book2-Differential-Equations.pdf", BOOK2)


def crowded_corpus() -> None:
    """doc13 and doc16 in the shape the real corpus has.

    doc13 carries six submittal percentages and dominates both the primary
    field and anything the recall pass would admit from a shared call. doc16
    carries the clause the question is about, buried past the default
    candidate pool behind forty-four verbose pages.
    """
    _document("d13", "doc13.pdf")
    _chunks("d13", "doc13.pdf",
            [(125, D13_PERCENT), *D13_OTHER_PERCENTS, *D16_FILLER[:4]])
    _document("d16", "doc16.pdf")
    _chunks("d16", "doc16.pdf",
            [(18, D16_PERCENT), *D16_FILLER, *D16_MORE_FILLER, *D16_DISTINCT])


def secret() -> None:
    """A document the caller is NOT granted, whose text would win outright."""
    _document("dx", "secret.pdf")
    _chunks("dx", "secret.pdf", [
        (1, "Design submittal percentages: the design submittal percentage "
            "schedule lists every design submittal percentage at 35% and 50% "
            "for each design submittal review."),
    ])


def _scope(*ids: str) -> access.AccessScope:
    return access.AccessScope(user_id="u", allowed_document_ids=frozenset(ids))


@pytest.fixture
def search_calls(monkeypatch):
    """Every call the analysis path makes to search(), with the two ways it
    can name documents to retrieval: the authorised scope, and a pinned
    document id (the percentage recall pass pins one per named document)."""
    calls: list[dict] = []
    real = analysis.search_mod.search

    def spy(question, **kwargs):
        calls.append({"allowed": kwargs["allowed_document_ids"],
                      "pinned": kwargs.get("document_id")})
        return real(question, **kwargs)

    monkeypatch.setattr(analysis.search_mod, "search", spy)
    return calls


def _filenames(evidence) -> set:
    return {e["filename"] for e in evidence}


QUESTION = "compare design submittal percentages in doc13.pdf and doc16.pdf"


# ---------------------------------------------------------- FAILURE 1: scoping


def test_a_third_document_that_would_otherwise_be_retrieved_is_excluded_by_naming():
    """The control run proves the textbook is genuinely competitive here. A
    test whose distractor was never retrieved in the first place would prove
    nothing about the narrowing."""
    corpus()
    scope = _scope("d13", "d16", "b2")

    unnamed, _ = analysis.gather(
        "compare design submittal percentages", scope, limit=8)
    assert "book2-Differential-Equations.pdf" in _filenames(unnamed), (
        "the textbook is not reachable for this question even without the "
        "narrowing, so the assertion below is vacuous - fix the fixture")

    named, result = analysis.gather(QUESTION, scope, limit=8)
    assert named, "the named question retrieved nothing; a refusal is not a fix"
    assert _filenames(named) == {"doc13.pdf", "doc16.pdf"}
    assert result["analysis_named_scope_applied"] is True
    assert result["analysis_named_documents"] == ["doc13.pdf", "doc16.pdf"]


def test_the_narrowed_scope_is_what_search_is_actually_given(search_calls):
    """Not a post-filter over a wider search. The document set search SEES is
    the narrowed one, so an excluded document cannot consume a candidate slot
    and push the answer out of it."""
    corpus()
    analysis.gather(QUESTION, _scope("d13", "d16", "b2"), limit=8)
    assert search_calls, "search was never called"
    for call in search_calls:
        assert call["allowed"] == frozenset({"d13", "d16"}), call


# ------------------------------- FAILURE 1: naming must not escalate access


def test_naming_a_document_the_caller_may_not_read_does_not_reach_it(search_calls):
    """THE ESCALATION TEST. secret.pdf answers the question better than either
    granted document and the question names it outright. It must not be
    searched, must not be cited, and must not appear in any scope the analysis
    path constructs."""
    corpus()
    secret()
    scope = _scope("d13", "d16")

    evidence, result = analysis.gather(
        "compare design submittal percentages in secret.pdf and doc13.pdf",
        scope, limit=8)

    assert "secret.pdf" not in _filenames(evidence)
    assert "dx" not in {e["document_id"] for e in evidence}
    assert not any("percentage schedule" in (e["exact_span"] or "").lower()
                   for e in evidence), "secret.pdf's text reached the ledger"
    assert len(search_calls) > 1, (
        "only one search call was made, so the recall pass - which pins a "
        "document id of its own - was never checked")
    for call in search_calls:
        assert "dx" not in call["allowed"], f"an unauthorised id reached search: {call}"
        assert call["allowed"] <= scope.allowed_document_ids, (
            "the narrowing widened the scope, which is the one thing it may "
            f"never do: {call}")
        assert call["pinned"] in (None, *scope.allowed_document_ids), (
            f"an unauthorised document was pinned by name: {call}")
    assert result["analysis_named_documents"] == ["doc13.pdf"], (
        "secret.pdf was treated as a name this caller may ask about")


def test_named_document_ids_never_leaves_the_scope():
    """The lookup that turns client-written text into document ids, on its own.
    Every name below exists in the corpus; only one of them is granted."""
    corpus()
    secret()
    scope = _scope("d13")
    assert analysis.named_document_ids(
        scope, ["doc13.pdf", "doc16.pdf", "secret.pdf"]) == frozenset({"d13"})
    assert analysis.named_document_ids(scope, ["secret.pdf"]) == frozenset()
    assert analysis.named_document_ids(scope, ["nothing-like-this.pdf"]) == frozenset()
    assert analysis.named_document_ids(access.empty_scope(), ["doc13.pdf"]) == frozenset()


# --------------------------------------- FAILURE 1: no narrowing to nothing


def test_when_no_name_resolves_the_full_authorised_scope_answers():
    """A false refusal is the worst outcome. A question whose only named file
    is one the caller may not read is answered from everything the caller MAY
    read, and records that the narrowing did not apply."""
    corpus()
    secret()
    scope = _scope("d13", "d16", "b2")

    evidence, result = analysis.gather(
        "what are the design submittal percentages in secret.pdf", scope,
        limit=8)

    assert evidence, "narrowing to nothing produced an empty answer"
    assert result["analysis_named_scope_applied"] is False
    assert result["analysis_named_documents"] == []
    assert "secret.pdf" not in _filenames(evidence)
    assert _filenames(evidence) <= {
        "doc13.pdf", "doc16.pdf", "book2-Differential-Equations.pdf"}


def test_narrow_to_named_falls_back_rather_than_returning_an_empty_set():
    corpus()
    scope = _scope("d13", "d16")
    assert analysis.narrow_to_named(scope, []) == (scope.allowed_document_ids, False)
    assert analysis.narrow_to_named(scope, ["absent.pdf"]) == (
        scope.allowed_document_ids, False)
    assert analysis.narrow_to_named(scope, ["doc16.pdf"]) == (frozenset({"d16"}), True)


# --------------------------------------------- FAILURE 2: the per-document cap


def _hit(document_id: str, n: int, text: str = "x") -> dict:
    return {"document_id": document_id, "filename": f"{document_id}.pdf",
            "page_start": n, "page_end": n, "section": None,
            "text": f"{text} {n}"}


def test_one_document_cannot_take_more_than_its_share_when_others_can_fill():
    """The measured failure as arithmetic: eighteen of twenty-four. With three
    documents holding candidates, the verbose one gets the cap and no more."""
    hits = ([_hit("verbose", i) for i in range(12)]
            + [_hit("other1", i) for i in range(3)]
            + [_hit("other2", i) for i in range(3)])
    kept = analysis.cap_per_document(hits, 6)
    cap = analysis.per_document_cap(6)
    assert len(kept) == 6
    assert sum(1 for h in kept if h["document_id"] == "verbose") == cap
    assert {h["document_id"] for h in kept} == {"verbose", "other1", "other2"}
    # the cap keeps each document's BEST, not an arbitrary sample
    assert [h["page_start"] for h in kept
            if h["document_id"] == "verbose"] == list(range(cap))


def test_at_the_measured_limit_the_cap_is_well_below_the_eighteen_that_hid_the_answer():
    assert analysis.per_document_cap(24) == 8
    assert analysis.per_document_cap(24) < 18


def test_a_single_document_field_lifts_the_cap_rather_than_shrinking_the_set():
    """A question only one document answers still gets a full set. A cap
    exists to stop one document crowding out another; with no other document
    there is nothing to protect, so the cap is lifted to the limit."""
    hits = [_hit("verbose", i) for i in range(12)]
    kept = analysis.cap_per_document(hits, 8)
    assert len(kept) == 8
    assert {h["document_id"] for h in kept} == {"verbose"}


def test_the_cap_is_never_topped_back_up_from_a_document_already_at_it():
    """THE DEFECT THIS TEST EXISTS FOR. The first version of the cap refilled
    leftover slots from the next-best passages, and because one document
    dominated the pool the fill handed the slots straight back to it: measured
    at limit=24 with cap=8, doc13 supplied 20 of 24. The set comes back SHORT
    instead."""
    hits = [_hit("verbose", i) for i in range(12)] + [_hit("other", i) for i in range(2)]
    kept = analysis.cap_per_document(hits, 8)
    cap = analysis.per_document_cap(8)
    assert sum(1 for h in kept if h["document_id"] == "verbose") == cap
    assert len(kept) == cap + 2, (
        "the leftover slots were filled from a document already at its cap")


def test_the_cap_invariant_holds_for_every_shape():
    """(a) never empty when there were passages, never longer than the limit;
    (b) no document over the cap unless it is the ONLY document, where the cap
    is lifted. (b) wins over the requested total."""
    shapes = [
        [_hit("a", 0)],
        [_hit("a", i) for i in range(3)],
        [_hit("a", i) for i in range(20)],
        [_hit("a", 0), _hit("b", 0)],
        [_hit("a", i) for i in range(9)] + [_hit("b", i) for i in range(2)],
        [_hit("a", i) for i in range(30)] + [_hit("b", i) for i in range(30)],
    ]
    for hits in shapes:
        documents = {h["document_id"] for h in hits}
        for limit in (1, 2, 3, 8, 24, 100):
            kept = analysis.cap_per_document(hits, limit)
            cap = limit if len(documents) < 2 else analysis.per_document_cap(limit)
            expected = min(limit, sum(
                min(cap, sum(1 for h in hits if h["document_id"] == d))
                for d in documents))
            assert kept, "a non-empty candidate set produced no passages"
            assert len(kept) == expected, (limit, len(hits), len(kept), expected)
            assert len(kept) <= limit
            for d in documents:
                assert sum(1 for h in kept if h["document_id"] == d) <= cap
    assert analysis.cap_per_document([], 8) == []


def test_the_cap_holds_on_the_returned_evidence_not_only_in_the_metadata():
    """THE VACUOUS-TEST FIX. The earlier version of this test asserted the cap
    at limit=4, where the other documents happened to fill every slot the cap
    freed - so it passed while the real corpus returned 20 of 24 passages from
    one document. It now asserts the share of the RETURNED EVIDENCE at a limit
    the dominant document could otherwise have swallowed.
    """
    crowded_corpus()
    evidence, result = analysis.gather(QUESTION, _scope("d13", "d16"), limit=24)
    cap = analysis.per_document_cap(24)
    assert cap == 8
    census = result["document_census"]
    assert census["d16"]["candidates"] > cap, (
        "doc16 contributed no more candidates than the cap, so nothing was "
        "capped and this test proves nothing")
    shares = {}
    for e in evidence:
        shares[e["filename"]] = shares.get(e["filename"], 0) + 1
    assert evidence, "the cap emptied the result set"
    assert shares == result["analysis_document_shares"], (
        "the reported shares do not describe the evidence that was returned")
    for filename, n in shares.items():
        assert n <= cap, f"{filename} supplied {n} of {len(evidence)}, cap {cap}"
    assert result["analysis_per_document_cap_lifted"] is False
    assert len(shares) >= 2, "one document still supplied the whole set"


def test_a_short_capped_set_is_reported_as_capped_and_is_never_empty():
    """The cap wins over the requested total, so the set comes back short -
    and short is not empty. A false refusal is still the worst outcome."""
    crowded_corpus()
    evidence, result = analysis.gather(QUESTION, _scope("d13", "d16"), limit=24)
    assert 0 < len(evidence) < 24, (
        "either the set was emptied, or the cap was topped back up to the limit")


# ------------------------------- FAILURE 3: percentages, and the false gap


def test_a_percentage_question_reaches_a_clause_whose_only_marker_is_50_percent():
    """doc16 p.18 carries "50%" and not the word "percentage", and sits behind
    forty-four verbose pages - past the default candidate pool. It has to be
    in the RETURNED EVIDENCE TEXT, not merely admitted somewhere."""
    assert "percent" not in D16_PERCENT.lower(), (
        "the fixture clause contains the word, so it proves nothing")
    crowded_corpus()
    evidence, result = analysis.gather(QUESTION, _scope("d13", "d16"), limit=8)
    assert result["analysis_percentage_candidates_added"] >= 1, (
        "the recall pass admitted nothing, so this fixture does not reproduce "
        "the defect and the assertion below proves nothing")
    spans = " || ".join(e["exact_span"] for e in evidence)
    assert "50% design submission" in spans, (
        "the clause the question was about is not in the evidence; got "
        f"{[(e['filename'], e['page_start']) for e in evidence]}")
    # and the other side is still represented, even at a cap of three
    assert any(e["filename"] == "doc13.pdf" and analysis.carries_percentage(e["exact_span"])
               for e in evidence), "doc13 contributed no percentage at all"


def test_both_sides_of_a_two_document_percentage_question_produce_both_clauses():
    """THE FALSE-GAP REGRESSION, as the real corpus states it.

    doc13 p.125 says "Concept/early Preliminary (35%) Design Submittal";
    doc16 p.18 says "a draft submission (usually at least a 50% design
    submission)". Both are in the corpus. When only one reaches the ledger,
    gap analysis honestly reports that a single document speaks to the facet -
    a compliance gap that does not exist. BOTH CLAUSE TEXTS must be there;
    "a percent-bearing passage from each side" is not the same claim and was
    satisfied while the real corpus returned neither clause.
    """
    crowded_corpus()
    # limit=24 is the configuration the defect was measured in. This fixture's
    # doc13 carries SIX submittal percentages where the real doc13's p.125
    # clause ranks among its best, so at limit=8 (cap 3) the fixture keeps
    # three of the six and not necessarily this one - which is a fair answer to
    # "compare percentages" and not the claim being made here. The claim is
    # about the two documents both reaching the ledger.
    evidence, _ = analysis.gather(QUESTION, _scope("d13", "d16"), limit=24)
    spans = " || ".join(e["exact_span"] for e in evidence)
    assert "Preliminary (35%)" in spans, "doc13's own percentage clause is missing"
    assert "50% design submission" in spans, "doc16's percentage clause is missing"
    percent_bearing = {
        e["filename"] for e in evidence
        if analysis.carries_percentage(e["exact_span"] or "")}
    assert percent_bearing == {"doc13.pdf", "doc16.pdf"}, percent_bearing


def test_the_recall_pass_reads_past_the_default_candidate_pool():
    """The clause sits at a bm25 rank the default candidate pool never reaches,
    so the DEPTH of the recall call is what makes it reachable at all.

    The fixture proves its own premise first: the clause's rank inside its own
    document, on the very query the recall pass issues, must be beyond
    `settings.search_candidates`. Without that check this test would pass on a
    fixture where the clause ranks first, which is how three mutations of the
    fix survived an earlier version of it.
    """
    crowded_corpus()
    widened = " ".join((QUESTION, *analysis._PERCENTAGE_TERMS))
    shallow = analysis.search_mod.search(
        widened, limit=200, candidates=settings.search_candidates,
        document_id="d16", rerank=False, dense=False,
        allowed_document_ids=frozenset({"d13", "d16"}))
    assert not any(h["chunk_id"] == "d16_c0" for h in shallow["hits"]), (
        f"the default candidate pool of {settings.search_candidates} already "
        "reaches the clause, so this fixture does not bury it and the "
        "assertion below proves nothing")
    admitted = analysis.percentage_recall(
        QUESTION, [], frozenset({"d13", "d16"}), None, 8, targets=["d16"])
    assert any("50% design submission" in (h.get("text") or "") for h in admitted), (
        "the recall pass did not reach the clause within its own document")


def test_the_recall_pass_gives_every_named_document_its_own_call():
    """A shared call is eaten by the verbose document: measured on the real
    corpus, one call over both returned 15 doc13 passages and 1 doc16."""
    crowded_corpus()
    shared = analysis.percentage_recall(
        QUESTION, [], frozenset({"d13", "d16"}), None, 8, targets=[None])
    split = analysis.percentage_recall(
        QUESTION, [], frozenset({"d13", "d16"}), None, 8, targets=["d13", "d16"])
    assert not any("50% design submission" in (h.get("text") or "") for h in shared), (
        "the shared call already reached the clause, so this fixture does not "
        "reproduce the starvation and the assertion below proves nothing")
    assert any("50% design submission" in (h.get("text") or "") for h in split)


def test_a_question_that_is_not_about_percentages_is_left_alone():
    """The widening must not fire on a question that did not ask for it."""
    corpus()
    _, result = analysis.gather(
        "what size must design submittal drawings be", _scope("d13", "d16"),
        limit=4)
    assert result["analysis_percentage_intent"] is False
    assert result["analysis_percentage_candidates_added"] == 0


def test_percentage_intent_reads_the_forms_an_engineer_types():
    for asked in ("what percentage of the design is complete",
                  "compare design submittal percentages",
                  "is a 50% submission required",
                  "what per cent of the drawings"):
        assert analysis.percentage_intent(asked), asked
    for asked in ("what is the smallest mechanical piping that must be modelled",
                  "which IFC coordination view is required"):
        assert not analysis.percentage_intent(asked), asked


def test_the_percentage_pass_admits_only_percent_bearing_passages_on_subject(monkeypatch):
    """It is additive and it is filtered. A second retrieval call widened by
    numbers could otherwise pull in a chalking rating or a page number."""
    supplementary = {"hits": [
        _hit("d16", 18, D16_PERCENT),                              # kept
        _hit("d16", 40, "The design package shall be complete."),  # no percent
        _hit("zz", 7, "Chalking rating 35% shall be preferred."),  # off subject
    ]}
    calls: list[str] = []

    def stub(question, **kwargs):
        calls.append(question)
        return supplementary

    monkeypatch.setattr(analysis.search_mod, "search", stub)
    primary = [_hit("d13", 125, D13_PERCENT)]
    out = analysis.percentage_recall(
        QUESTION, primary, frozenset({"d13", "d16"}), None, 24)

    assert calls and calls[0] != QUESTION, (
        "the supplementary call must not re-ask the original question verbatim")
    assert QUESTION in calls[0], "the question's own words were dropped"
    assert out[: len(primary)] == primary, "the primary field was reordered"
    added = [h["text"] for h in out[len(primary):]]
    assert any("50% design submission" in t for t in added)
    assert not any("Chalking" in t for t in added)
    assert not any("shall be complete" in t for t in added)


def test_percent_bearing_passages_sort_first_and_nothing_is_lost():
    hits = [_hit("a", 1, "no figure here"), _hit("b", 2, "at least a 50% design"),
            _hit("a", 3, "still no figure"), _hit("b", 4, "a 35% submittal")]
    out = analysis.percentage_first(hits)
    assert [h["page_start"] for h in out] == [2, 4, 1, 3], (
        "stable within both groups, so retrieval rank survives")
    assert sorted(id(h) for h in out) == sorted(id(h) for h in hits)
