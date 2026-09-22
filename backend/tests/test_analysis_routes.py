"""The three analysis routes: scoped, model-injected, and honest when refusing.

`synthesis.py` and `claims.py` have their own suites and are pure. This file
covers only what joining them to retrieval, HTTP and the access scope can get
wrong - which is where the interesting failures live, because the engines were
developed in a sandbox against shims and had never seen a real scope, a real
search result or the real `context_budget`.

Every model call is injected. A test that needed Ollama running would be a test
that gets skipped on the machine where it matters.
"""

from __future__ import annotations

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import access, analysis, db, keyword, synthesis
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

VIBRATION = [
    "5.3.2 Vibration Limits",
    "Vibration limits per API 610 shall not exceed 3.0 mm/s RMS measured at the",
    "bearing housing of pump P-101A during continuous operation at rated flow,",
    "and any exceedance shall be reported to the area engineer before the pump",
    "is returned to service under the procedure given in this specification.",
]
COATING = [
    "A.1 Coating system no. 1",
    "Coating system no. 1 shall have a nominal dry film thickness of 280 um",
    "applied over a near-white metal blast cleaned surface for all carbon steel",
    "substrates operating below 120 degrees C in offshore atmospheric service.",
]
#: A SECOND on-topic passage, for the tests that need generation to happen
#: (B7). With only VIBRATION and COATING, the relevance floor (5a7a2b3) rightly
#: drops the vibration page for a thickness question, leaving ONE passage -
#: and synthesis passes a single passage through without calling the model,
#: so those tests never reached the code they were written to test.
COATING_INSPECTION = [
    "A.4 Coating inspection",
    "The dry film thickness of coating system no. 1 shall be measured after",
    "curing with a calibrated gauge, and no reading may fall below 280 um on",
    "any carbon steel surface accepted for offshore atmospheric service.",
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


def build(path, blocks):
    doc = pymupdf.open()
    for block in blocks:
        page = doc.new_page()
        for i, line in enumerate(block):
            page.insert_text((72, 100 + i * 16), line)
    doc.save(str(path))
    doc.close()
    return path


def ingest(name="spec.pdf", blocks=(VIBRATION, COATING)) -> str:
    client = TestClient(app)
    path = build(settings.data_dir / name, blocks)
    with open(path, "rb") as fh:
        doc_id = client.post("/api/documents",
                             files={"file": (name, fh, "application/pdf")}
                             ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    return doc_id


def ingest_for_generation(question: str) -> str:
    """Ingest two on-topic passages and prove the model WILL be called.

    The inspection passage is a SEPARATE document: as a third page of the
    same PDF the chunker merged it with the coating page into one passage.

    The precondition is the point: B7 was four tests silently testing the
    single-passage pass-through instead of generation, because nothing
    asserted how much evidence reached the synthesiser."""
    doc_id = ingest()
    ingest("inspection.pdf", (COATING_INSPECTION,))
    evidence, _ = analysis.gather(question, access.unrestricted_scope())
    assert len(evidence) >= 2, (
        f"{len(evidence)} passage(s) survived retrieval - synthesis would pass "
        "it through without calling the model, and this test would prove nothing")
    return doc_id


def fake_generate(text: str, truncated: bool = False):
    def generate(system: str, prompt: str) -> synthesis.Generation:
        return synthesis.Generation(text=text, truncated=truncated)
    return generate


# ---------------------------------------------------------------- evidence


def test_evidence_id_survives_rechunking_because_it_is_not_a_chunk_id():
    """A citation that moves when the chunker is retuned is not a citation."""
    hit = {"document_id": "doc_1", "page_start": 17, "page_end": 17,
           "section": "A.1", "text": "Coating system no. 1 shall be 280 um."}
    first = analysis.evidence_id(hit)
    # a re-chunk changes the chunk id and nothing this id is built from
    assert analysis.evidence_id({**hit, "chunk_id": "different"}) == first
    # a different span on the same page is different evidence
    assert analysis.evidence_id({**hit, "text": "Something else."}) != first


def test_the_span_is_the_documents_own_text_not_a_reflow():
    ingest()
    evidence, _ = analysis.gather("what is the dry film thickness",
                                  access.unrestricted_scope())
    assert evidence, "retrieval returned nothing - nothing below is measured"
    for item in evidence:
        assert item["exact_span"].strip(), "an empty span cannot be quoted"
        assert item["text_source"] in ("extracted", "recognised")
        # never 0.0 as a stand-in: 0.0 is above the -3.0 floor
        assert item["relevance_score"] is None or isinstance(
            item["relevance_score"], float)
        # WHICH SCALE, not a bare number - a rerank score and an RRF score are
        # not comparable.
        assert (item["relevance_score_type"] is None) == (
            item["relevance_score"] is None)


# ------------------------------------------------------------------- scope


def _user(email, role_id, doc_ids):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = db.connect()
    uid = f"user_{email.split('@')[0]}"
    with conn:
        conn.execute("INSERT OR IGNORE INTO roles (id, name, description, created_at) "
                     "VALUES (?, ?, '', ?)", (role_id, role_id, now))
        conn.execute("INSERT INTO users (id, email, display_name, password_hash, "
                     "is_active, created_at) VALUES (?, ?, ?, 'x', 1, ?)",
                     (uid, email, email, now))
        conn.execute("INSERT OR IGNORE INTO user_roles (user_id, role_id, granted_at) "
                     "VALUES (?, ?, ?)", (uid, role_id, now))
        for d in doc_ids:
            conn.execute("INSERT INTO document_role_access (document_id, role_id, "
                         "granted_at) VALUES (?, ?, ?)", (d, role_id, now))
    return uid


def test_evidence_never_leaves_the_callers_scope(monkeypatch):
    visible = ingest("visible.pdf", (COATING,))
    hidden = ingest("hidden.pdf", (VIBRATION,))
    assert visible != hidden, "the two uploads deduplicated - every test below is vacuous"

    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    uid = _user("a@x.test", "role_a", [visible])
    scope = access.scope_for_user(uid)
    assert scope.allowed_document_ids == {visible}

    evidence, _ = analysis.gather("vibration limits and coating thickness", scope)
    assert evidence, "nothing retrieved - the leak below would be invisible"
    assert {e["document_id"] for e in evidence} == {visible}
    assert not any("hidden.pdf" == e["filename"] for e in evidence)


def test_an_unscoped_caller_gets_no_evidence_rather_than_everything(monkeypatch):
    ingest()
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    evidence, _ = analysis.gather("dry film thickness", access.empty_scope())
    assert evidence == []


def test_a_baseline_the_caller_may_not_read_is_404(monkeypatch):
    hidden = ingest("hidden.pdf", (COATING,))
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    stranger = _user("c@x.test", "role_c", [])
    monkeypatch.setattr(access, "_resolve_user_id", lambda request: stranger)
    r = TestClient(app).post("/api/analysis/gaps",
                             json={"question": "thickness",
                                   "baseline_document_id": hidden})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "not_found"


# ------------------------------------------------------------------ stage 3


def test_a_sentence_whose_number_is_in_no_cited_span_is_dropped_not_flagged():
    """The ruling: dropped. A flag still puts the number on screen, and the
    reader takes the number. The loss is reported, never silent."""
    ingest_for_generation("what is the dry film thickness")
    out = analysis.summary(
        "what is the dry film thickness", access.unrestricted_scope(),
        generate=fake_generate(
            "The coating is 280 um thick [S1]. The limit is 999 um [S1]."),
    )
    assert out["summary"] is not None
    assert "999" not in out["summary"], "an unsupported number reached the reader"
    reasons = [d["reason"] for d in out["removed"]]
    assert "value 999 not in cited passage" in reasons, reasons


def test_an_uncited_sentence_never_reaches_the_prose():
    ingest_for_generation("what is the dry film thickness")
    out = analysis.summary(
        "what is the dry film thickness", access.unrestricted_scope(),
        generate=fake_generate("Coatings are important. The thickness is 280 um [S1]."),
    )
    assert "Coatings are important" not in (out["summary"] or "")
    assert any(d["reason"] == "cites no supplied source"
               for d in out["removed"])


def test_the_route_names_what_it_does_not_produce():
    ingest()
    out = analysis.summary("dry film thickness", access.unrestricted_scope(),
                           generate=fake_generate("The thickness is 280 um [S1]."))
    assert out["not_implemented_sections"], "an absent section must be visible as absent"
    assert any("revision" in s for s in out["not_implemented_sections"])


def test_an_unreachable_model_is_503_and_not_a_crash(monkeypatch):
    import httpx

    ingest_for_generation("thickness")

    def boom(system, prompt):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(analysis, "ollama_generate", boom)
    r = TestClient(app).post("/api/analysis/summary", json={"question": "thickness"})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "model_unavailable"


# ------------------------------------------------------------------ stage 6


def test_gaps_needs_no_model_at_all(monkeypatch):
    """A mechanical comparison must not depend on a model being up."""
    import httpx

    ingest()

    def boom(*a, **k):
        raise AssertionError("gaps called the model")

    monkeypatch.setattr(analysis, "ollama_generate", boom)
    monkeypatch.setattr(httpx.Client, "request", boom)
    out = analysis.gaps("dry film thickness", access.unrestricted_scope())
    assert out["gaps"]["applicability"] == "not_applicable"


def test_the_system_never_chooses_the_baseline():
    """Picking one - the oldest document, the one named 'standard' - would be
    an engineering judgement the system has no basis for."""
    ingest()
    out = analysis.gaps("dry film thickness", access.unrestricted_scope())
    assert out["gaps"]["baseline"] is None
    assert out["gaps"]["applicability"] == "not_applicable"
    for item in out["gaps"]["items"]:
        assert item["status"] != "met", (
            "a facet was reported as met with no baseline to meet")
        assert item["baseline_citation_id"] is None


def test_a_named_baseline_makes_the_comparison_applicable():
    doc_id = ingest()
    out = analysis.gaps("dry film thickness", access.unrestricted_scope(),
                        baseline_document_id=doc_id)
    assert out["gaps"]["applicability"] == "applicable"
    assert out["gaps"]["baseline"]["document_id"] == doc_id


# ------------------------------------------------------------------ stage 4


def test_confidence_is_never_high_and_names_the_checks_that_fired():
    ingest_for_generation("what is the dry film thickness")
    out = analysis.recommendation(
        "what is the dry film thickness", access.unrestricted_scope(),
        generate=fake_generate("Verify the thickness against the datasheet [S1]."),
    )
    rec = out["recommendation"]
    assert rec is not None
    assert rec["confidence"] in ("low", "medium"), rec["confidence"]
    assert rec["checks"], "a confidence with no checks behind it is a number"
    assert all(set(c) == {"label", "fired"} for c in rec["checks"])


def test_a_recommendation_never_says_a_design_is_compliant_or_approved():
    """The system advises what to verify. It does not certify."""
    ingest()
    out = analysis.recommendation(
        "is the coating compliant", access.unrestricted_scope(),
        generate=fake_generate("The coating is 280 um [S1]."),
    )
    text = (out["recommendation"] or {}).get("text", "")
    for word in ("is compliant", "is approved", "is safe", "certified"):
        assert word not in text.lower()


def test_market_findings_on_a_recommendation_are_all_samples():
    """The panel rides along on this response; a sample must stay a sample."""
    ingest()
    out = analysis.recommendation(
        "coating cost", access.unrestricted_scope(),
        generate=fake_generate("Verify the price against a quotation [S1]."),
    )
    rows = out["public_market_findings"]
    assert rows, "no rows - an empty panel reads as a measurement"
    assert all(r["is_sample"] is True for r in rows)
    assert all(r["url"].startswith("sample://") for r in rows)


# ------------------------------------------- through the route, not around it


def test_a_real_summary_serialises_through_the_response_model(monkeypatch):
    """The test that would have caught a schema this file did not have.

    Every other test here calls `analysis.summary()` directly, so the route's
    `response_model` never validated a real result - and it would have failed:
    the schema said `DocumentedFinding.text` while the engine emits `claim`.
    A 500 on the first real summary, invisible to a suite that never went
    through FastAPI.
    """
    ingest()
    monkeypatch.setattr(
        analysis, "ollama_generate",
        fake_generate("The dry film thickness is 280 um [S1]. "
                      "Surface preparation is specified [S2]."))
    r = TestClient(app).post("/api/analysis/summary",
                             json={"question": "what is the dry film thickness"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["evidence_ledger"], "no evidence - nothing below is measured"
    for item in body["evidence_ledger"]:
        # Every claim on screen carries a document and a page.
        assert item["document_id"] and item["page_start"] is not None
        # WHICH SCALE, not a bare number.
        if item["relevance_score"] is None:
            assert item["relevance_score_type"] is None
        else:
            assert item["relevance_score_type"] == "rerank"
    for finding in body["documented_findings"]:
        assert finding["claim"] and finding["citation_ids"]
        assert finding["source_kind"] == "document"


def test_a_real_gaps_response_serialises_and_carries_document_and_page(monkeypatch):
    ingest()
    r = TestClient(app).post("/api/analysis/gaps", json={"question": "thickness"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["gaps"]["applicability"] in (
        "applicable", "not_applicable", "insufficient_baseline")
    for item in body["evidence_ledger"]:
        assert item["document_id"] and item["page_start"] is not None


def test_a_real_recommendation_serialises_and_is_never_high(monkeypatch):
    ingest()
    monkeypatch.setattr(
        analysis, "ollama_generate",
        fake_generate("Verify the thickness against the datasheet [S1]."))
    r = TestClient(app).post("/api/analysis/recommendations",
                             json={"question": "coating thickness"})
    assert r.status_code == 200, r.text
    rec = r.json()["recommendation"]
    if rec is not None:
        assert rec["confidence"] in ("low", "medium", None), rec["confidence"]
        assert rec["confidence"] != "high"


# --------------------------------------------------- the finding must lead
#
# These build the cluster list directly rather than ingesting a two-page
# fixture. The first version ingested the small fixture and passed against the
# UNFIXED code, because a corpus with one facet cannot bury anything - the
# test was measuring nothing. This one reproduces the shape that was actually
# reported: several facets, alphabetically ahead of the answer.


def _spans(*sentences):
    return [{"evidence_id": f"ev{i}", "filename": "NORSOK.pdf", "page_start": 9 + i,
             "page_end": 9 + i, "section": None, "exact_span": s,
             "text_source": "extracted"}
            for i, s in enumerate(sentences)]


BURIAL = _spans(
    "Adhesion shall show maximum 50 % reduction from the original value.",
    "The coating shall have a minimum adhesion of 2,0 MPa when tested.",
    "Minimum coating thickness for structural items shall be 125 um.",
    "Coating system no. 1 shall be applied to all external surfaces.",
)


def _items(question, evidence):
    from app import claims as claims_mod

    rows = claims_mod.extract_claims(evidence, allowed_document_ids=_scope())
    clusters = claims_mod.cluster(rows, claims_mod.question_terms(question, allowed_document_ids=_scope()))
    return analysis._gap_items(clusters, None,
                               {e["evidence_id"]: "doc_1" for e in evidence})


def test_the_answer_is_not_buried_under_nothing_to_compare():
    """A measured facet the question asked about comes FIRST.

    Reported: "Minimum coating thickness ... 125 um" arrived sixth of
    fourteen, under items reading "Only one document speaks to this facet".
    Alphabetical order is what put "coating (%)" above "coating thickness
    (um)" on a question about coating thickness.
    """
    items = _items("what is the minimum coating thickness required", BURIAL)
    assert items, "no gap items - nothing below is measured"
    assert "thickness" in items[0]["facet"], (
        f"the answer did not lead; got {[i['facet'] for i in items]}")


def test_facets_that_answer_less_of_the_question_come_after():
    """Guard the guard: the burial case must actually contain a facet that
    alphabetical order would have put first."""
    items = _items("what is the minimum coating thickness required", BURIAL)
    facets = [i["facet"] for i in items]
    assert len(facets) > 1, f"only one facet - nothing could be buried: {facets}"
    assert sorted(facets) != facets, (
        "the facets happen to be in alphabetical order, so this case cannot "
        f"distinguish the two orderings: {facets}")


def test_a_citation_is_never_listed_twice_in_one_item():
    """One evidence id appeared five times in a single item, which reads as
    five sources and is one."""
    # ONE evidence item, several sentences about the same facet - which is
    # how the duplicate actually arose. Three separate ids could never
    # collide, so a fixture built that way proves nothing.
    repeated = [{
        "evidence_id": "7a86abdc251ea774", "filename": "NORSOK.pdf",
        "page_start": 9, "page_end": 9, "section": None,
        "text_source": "extracted",
        "exact_span": (
            "The coating thickness shall be 125 um. "
            "The coating thickness shall be 150 um for splash zones. "
            "The coating thickness shall be 200 um where immersed."),
    }, {
        "evidence_id": "other", "filename": "OTHER.pdf",
        "page_start": 3, "page_end": 3, "section": None,
        "text_source": "extracted",
        "exact_span": "The coating thickness shall be 280 um.",
    }]
    items = _items("coating thickness", repeated)
    assert any(len(i["project_citation_ids"]) for i in items), (
        "no item cited anything - the duplicate could not have appeared")
    for item in items:
        ids = item["project_citation_ids"]
        assert len(ids) == len(set(ids)), f"{item['facet']}: {ids}"


def test_unmeasured_singletons_collapse_into_one_entry_at_the_end():
    unmeasured = _spans(
        "Coating system no. 1 shall be applied to external surfaces.",
        "Coating system no. 2 shall be applied to internal surfaces.",
        "Minimum coating thickness shall be 125 um.",
    )
    items = _items("coating system", unmeasured)
    collapsed = [i for i in items if i["facet"].startswith("stated once")]
    assert len(collapsed) <= 1
    if collapsed:
        assert items[-1] is collapsed[0], (
            "the group that says 'nothing to compare' must come last")


def test_without_a_baseline_nothing_claims_to_be_met_or_a_gap():
    """"met" and "possible_gap" both mean measured against the authority, and
    with none named neither can be assessed. A disagreement between two
    documents is still knowable, so `conflict` survives."""
    for item in _items("coating thickness", BURIAL):
        assert item["status"] not in ("met", "possible_gap"), item


# ------------------------------------------- a status that matches its note


def _items_with_baseline(question, evidence, baseline_ids, doc_of=None):
    """Gap items WITH a baseline named, which is when met/possible_gap apply."""
    from app import claims as claims_mod

    rows = claims_mod.extract_claims(evidence, allowed_document_ids=_scope())
    clusters = claims_mod.cluster(rows, claims_mod.question_terms(question, allowed_document_ids=_scope()))
    document_of = doc_of or {
        e["evidence_id"]: ("doc_base" if e["evidence_id"] in baseline_ids else "doc_other")
        for e in evidence
    }
    return analysis._gap_items(clusters, "doc_base", document_of)


#: A real "addition" cluster, verified rather than assumed: same facet, same
#: dimension, no contradiction - the second row simply carries an IDENTIFIER
#: (ISO 12944) the first lacks, which is what makes `label_cluster` return
#: "addition" with the note "One row carries a measurement or identifier the
#: others lack; nothing is contradicted."
#:
#: The first version of this fixture used prose with no measurement at all and
#: produced ZERO claims - a claim needs a measurement or an identifier to
#: exist. The vacuity guard below caught it.
ADDITION = _spans(
    "Minimum coating thickness shall be 125 um.",
    "Coating thickness shall be 125 um per ISO 12944.",
)


def test_an_addition_is_not_reported_as_a_possible_gap():
    """THE ROW CONTRADICTED ITSELF. Measured live: facet 'drawings', status
    "possible_gap" - "Retrieval found nothing addressing this" - above the note
    "One row carries a measurement or identifier the others lack; nothing is
    contradicted." A reader cannot reconcile those.

    "addition" means one row says MORE than the others, which is the opposite
    of retrieval finding nothing. When the project documents DO speak to the
    facet, the honest status is the one that already means "addressed, nothing
    contradicted" - which is what `met` means here, since `agreement` maps to
    it on the same basis.
    """
    items = _items_with_baseline("coating thickness", ADDITION, {"ev0"})
    addition = [i for i in items if i["note"] and "nothing is contradicted" in i["note"]]
    assert addition, "the fixture produced no addition cluster; this test would be vacuous"
    for item in addition:
        assert item["status"] != "possible_gap", (
            f"{item['facet']!r} is reported as a possible gap while its own note "
            f"says nothing is contradicted: {item['note']!r}")
        assert item["status"] == "met", item


def test_a_baseline_speaking_alone_is_still_a_possible_gap():
    """The other half, and the reason this is not a blanket remap.

    A cluster whose only row IS the baseline means no project document
    addressed it - which is exactly what `possible_gap` is for. Without this
    the fix would silence the finding the panel exists to make.
    """
    alone = _spans("Minimum coating thickness shall be 125 um.")
    items = _items_with_baseline("coating thickness", alone, {"ev0"})
    assert items, "no items produced"
    assert all(i["status"] == "possible_gap" for i in items), items


def test_an_unnormalisable_unit_is_insufficient_evidence_not_a_gap():
    """`unresolved` also fell through to possible_gap. It means the values
    could not be COMPARED, not that retrieval found nothing - and
    `insufficient_evidence` says precisely that."""
    from app import claims as claims_mod

    rows = claims_mod.extract_claims(_spans("Torque shall be 40 klbf-ft at the flange."), allowed_document_ids=_scope())
    clusters = claims_mod.cluster(rows, claims_mod.question_terms("torque", allowed_document_ids=_scope()))
    unresolved = [c for c in clusters if c.label == "unresolved"]
    if not unresolved:
        pytest.skip("this corpus fixture produced no unresolvable unit; "
                    "the mapping is asserted directly below instead")
    items = analysis._gap_items(unresolved, "doc_base",
                                {"ev0": "doc_base"})
    assert all(i["status"] == "insufficient_evidence" for i in items), items


def test_the_label_to_status_mapping_is_exhaustive_and_honest():
    """Every label `claims.label_cluster` can return has a deliberate status.

    Asserted directly so a new label added to claims.py cannot fall through to
    `possible_gap` unnoticed - which is how `addition` and `unresolved` both
    came to claim that retrieval found nothing.
    """
    assert analysis.STATUS_FOR_LABEL == {
        "possible_conflict": "conflict",
        "agreement": "met",
        "addition": "met",
        "unresolved": "insufficient_evidence",
    }


def _scope():
    """Corpus-wide scope, stated explicitly.

    `extract_claims` and `question_terms` reach `lexical.distinctive_terms`,
    which consults the corpus and now REQUIRES a scope with no default.
    """
    from app.search import every_document_id
    return every_document_id()
