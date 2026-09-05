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

import fitz
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
    doc = fitz.open()
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
        assert item["rerank_score"] is None or isinstance(item["rerank_score"], float)


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
    ingest()
    out = analysis.summary(
        "what is the dry film thickness", access.unrestricted_scope(),
        generate=fake_generate(
            "The coating is 280 um thick [S1]. The limit is 999 um [S1]."),
    )
    assert out["summary"] is not None
    assert "999" not in out["summary"], "an unsupported number reached the reader"
    reasons = [d["reason"] for d in out["dropped_sentences"]]
    assert any("number no cited span contains" in r for r in reasons), reasons


def test_an_uncited_sentence_never_reaches_the_prose():
    ingest()
    out = analysis.summary(
        "what is the dry film thickness", access.unrestricted_scope(),
        generate=fake_generate("Coatings are important. The thickness is 280 um [S1]."),
    )
    assert "Coatings are important" not in (out["summary"] or "")
    assert any(d["reason"] == "cites no supplied source"
               for d in out["dropped_sentences"])


def test_the_route_names_what_it_does_not_produce():
    ingest()
    out = analysis.summary("dry film thickness", access.unrestricted_scope(),
                           generate=fake_generate("The thickness is 280 um [S1]."))
    assert out["not_implemented_sections"], "an absent section must be visible as absent"
    assert any("revision" in s for s in out["not_implemented_sections"])


def test_an_unreachable_model_is_503_and_not_a_crash(monkeypatch):
    import httpx

    ingest()

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
    ingest()
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
