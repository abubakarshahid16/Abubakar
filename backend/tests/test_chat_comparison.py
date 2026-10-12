"""Plan C3 (docs/chat-requirements-b6c-b9.md): "compare X and Y" retrieves for
EACH named side separately, cites both sides, and never says a standard
"does not mention" something unless the targeted search on that side found
nothing - it says "not found in the pages read" instead.

Evidence recorded 2026-10-01: a comparison question retrieved ONE shared
top-k across every named standard, so one standard's passages crowded another
out of the ranking, and the model was free to word the resulting gap however
it liked - including "does not mention", indistinguishable from a genuine
targeted search that came back empty. It was not: the search never ran for
that side. Fixed by retrieving each named side on its own top-k budget
(`chat_comparison.compare`) and writing the one "not found" sentence in code,
never in the model's own words.
"""

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import chat_comparison, db, keyword
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

#: SAES-W-010's own pages: states a post weld heat treatment temperature.
PWHT_TEMPERATURE = [
    "13.12 Post Weld Heat Treatment",
    "Post weld heat treatment of carbon steel welds shall be carried out at a",
    "minimum holding temperature of 620 degrees C, held for one hour per 25 mm",
    "of thickness, and recorded on a calibrated chart for the welding engineer",
    "to review before the joint is released for the next stage of fabrication.",
]

#: ASME-B31-3's own pages: a real clause, but never touches PWHT temperature.
SCOPE_ONLY = [
    "300 General Statements",
    "This Code prescribes requirements for materials, design, fabrication,",
    "assembly, erection, examination, inspection and testing of piping subject",
    "to the rules of this Code, applicable to process plant piping systems",
    "within the property or site boundary of a facility covered by the owner.",
]

#: Neither standard's pages mention hydrotest sequencing at all.
NO_HYDROTEST_A = [
    "4.1 Materials",
    "Materials for pressure-containing parts shall conform to the material",
    "specifications listed in the applicable material tables of this section",
    "and shall carry full traceability to the original mill certificate issued",
    "by the manufacturer at the time the material was first supplied.",
]
NO_HYDROTEST_B = [
    "2.1 Definitions",
    "For the purpose of this specification the following definitions apply",
    "to every clause below, and a term not defined here carries the meaning",
    "given to it by the general engineering usage current in the industry",
    "at the time this specification was issued for use on the project.",
]

#: A THIRD, unrelated document naming neither side - carries the same fact as
#: SAES-W-010, to prove the fact must not leak in through the wrong document.
DECOY_WITH_SAME_FACT = [
    "9.1 Unrelated Clause",
    "Some other unrelated procedure also happens to specify a minimum holding",
    "temperature of 620 degrees C, held for one hour per 25 mm of thickness,",
    "for a completely different purpose than post weld heat treatment on the",
    "welds this comparison was actually asked about by the reader.",
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


def _scope():
    from app.search import every_document_id
    return every_document_id()


# --------------------------------------------------------- trigger detection


def test_a_plain_question_is_not_a_comparison():
    assert not chat_comparison.is_comparison_question(
        "what does SAES-W-010 say about post weld heat treatment")


@pytest.mark.parametrize("question", [
    "compare SAES-W-010 and ASME-B31-3 on post weld heat treatment",
    "SAES-W-010 versus ASME-B31-3 on hydrotest sequencing",
    "SAES-W-010 vs ASME-B31-3",
])
def test_a_comparison_question_is_recognised(question):
    assert chat_comparison.is_comparison_question(question)


def test_fewer_than_two_named_sides_is_not_a_comparison_to_split():
    documents = {"d1": "SAES-W-010.pdf"}
    assert chat_comparison.named_sides(
        "compare SAES-W-010 with itself", documents) is None


# ------------------------------------------ (1) a fact present on one side


def test_a_fact_present_on_only_one_side_is_cited_there_and_not_invented_on_the_other():
    client = TestClient(app)
    a_id = upload(client, [PWHT_TEMPERATURE], "SAES-W-010.pdf")
    b_id = upload(client, [SCOPE_ONLY], "ASME-B31-3.pdf")

    sides = chat_comparison.named_sides(
        "compare SAES-W-010 and ASME-B31-3 on the post weld heat treatment temperature",
        {a_id: "SAES-W-010.pdf", b_id: "ASME-B31-3.pdf"})
    assert sides is not None and len(sides) == 2

    result = chat_comparison.compare(
        "compare SAES-W-010 and ASME-B31-3 on the post weld heat treatment temperature",
        sides, tier="extract", allowed_document_ids=_scope(),
        progress_id=None, model=None, history="")

    assert result["answer_type"] == "comparison"
    by_name = {s["name"]: s for s in result["comparison"]["sides"]}
    assert by_name["SAES-W-010"]["answer_type"] == "extract"
    assert by_name["ASME-B31-3"]["answer_type"] == "insufficient_evidence"

    # THE FOUND FACT IS CITED, from the side that actually has it.
    assert "620" in result["answer"]
    found_passage_docs = {p["document_id"] for p in result["passages"]}
    assert a_id in found_passage_docs
    assert b_id not in found_passage_docs

    # THE MISSING SIDE'S WORDING IS THE ONE THIS FILE WRITES, never a model's
    # own words for an absence.
    assert "ASME-B31-3: not found in the pages read." in result["answer"]
    assert "does not mention" not in result["answer"].lower()
    assert "does not say" not in result["answer"].lower()


# --------------------------------------------------------- (2) an absence


def test_an_absence_on_both_sides_says_not_found_never_does_not_mention():
    client = TestClient(app)
    a_id = upload(client, [NO_HYDROTEST_A], "SAES-W-010.pdf")
    b_id = upload(client, [NO_HYDROTEST_B], "ASME-B31-3.pdf")

    sides = chat_comparison.named_sides(
        "compare SAES-W-010 and ASME-B31-3 on hydrotest sequencing",
        {a_id: "SAES-W-010.pdf", b_id: "ASME-B31-3.pdf"})
    result = chat_comparison.compare(
        "compare SAES-W-010 and ASME-B31-3 on hydrotest sequencing",
        sides, tier="extract", allowed_document_ids=_scope(),
        progress_id=None, model=None, history="")

    by_name = {s["name"]: s for s in result["comparison"]["sides"]}
    assert by_name["SAES-W-010"]["answer_type"] == "insufficient_evidence"
    assert by_name["ASME-B31-3"]["answer_type"] == "insufficient_evidence"
    assert "SAES-W-010: not found in the pages read." in result["answer"]
    assert "ASME-B31-3: not found in the pages read." in result["answer"]
    assert "does not mention" not in result["answer"].lower()
    assert result["passages"] == []


# ------------------------------------------------- (3) a named-standard filter


def test_a_named_standard_only_searches_within_its_own_named_side():
    """THE SCOPING GUARD: a fact sitting in a THIRD document that neither
    side named must never leak into either side's answer or citations - the
    per-side scope is an intersection with the named ids, never the caller's
    whole permission (CLAUDE.md rule 5), reusing the same named-document
    matching Task 0 relies on."""
    client = TestClient(app)
    a_id = upload(client, [SCOPE_ONLY], "SAES-W-010.pdf")
    b_id = upload(client, [SCOPE_ONLY], "ASME-B31-3.pdf")
    decoy_id = upload(client, [DECOY_WITH_SAME_FACT], "unrelated-spec.pdf")

    sides = chat_comparison.named_sides(
        "compare SAES-W-010 and ASME-B31-3 on the post weld heat treatment temperature",
        {a_id: "SAES-W-010.pdf", b_id: "ASME-B31-3.pdf", decoy_id: "unrelated-spec.pdf"})
    assert len(sides) == 2
    named_ids = {i for _, ids in sides for i in ids}
    assert decoy_id not in named_ids

    result = chat_comparison.compare(
        "compare SAES-W-010 and ASME-B31-3 on the post weld heat treatment temperature",
        sides, tier="extract", allowed_document_ids=_scope(),
        progress_id=None, model=None, history="")

    assert decoy_id not in {p["document_id"] for p in result["passages"]}
    assert "620" not in result["answer"]
    assert "SAES-W-010: not found in the pages read." in result["answer"]
    assert "ASME-B31-3: not found in the pages read." in result["answer"]


# --------------------------------------------------------------- end to end


def test_the_chat_route_answers_a_comparison_from_both_named_sides():
    """THE MUTATION TARGET: wired all the way through `chat.ask`, not just
    the helper - a comparison-shaped question naming two indexed standards
    reaches `chat_comparison.compare`, never one shared, single retrieval."""
    client = TestClient(app)
    upload(client, [PWHT_TEMPERATURE], "SAES-W-010.pdf")
    upload(client, [SCOPE_ONLY], "ASME-B31-3.pdf")
    convo = client.post("/api/conversations").json()

    body = client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "compare SAES-W-010 and ASME-B31-3 on the post "
                          "weld heat treatment temperature"},
    ).json()

    assert body["answer_type"] == "comparison"
    assert body["comparison"] is not None
    names = {s["name"] for s in body["comparison"]["sides"]}
    assert names == {"SAES-W-010", "ASME-B31-3"}
    assert "620" in body["answer"]
    assert "ASME-B31-3: not found in the pages read." in body["answer"]

    # REOPENED, the side breakdown survives (chat._PAYLOAD_KEYS).
    reopened = client.get(f"/api/conversations/{convo['id']}").json()
    assistant = [m for m in reopened["messages"] if m["role"] == "assistant"][-1]
    assert assistant["payload"]["comparison"]["sides"]
