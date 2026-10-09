"""#679 (W5b-04): review a written procedure (HAZOP, SIL) against a playbook.
INVENTED documents only (tests/docx_builder.py); no client text, no reserved
Word document, no hidden-exam material.

Mutations: M4701-M4732 (scripts/mutations/w5b_679_playbooks.py).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import access, ai_task_runner as runner, chunker, db, extract, keyword, playbooks, upload
from app.config import settings
from app.main import app
from app.reasoning_provider import Response
from tests import docx_builder as d
from tests.fake_tokenizer import install_if_missing

REPO = Path(__file__).resolve().parents[2]
PLAYBOOK_DIR = REPO / "backend" / "app" / "reference" / "playbooks"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "w5b679.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "docx_input_enabled", True)
    install_if_missing(monkeypatch)
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    runner.TASKS.clear()
    yield
    runner.TASKS.clear()


# ----------------------------------------------------------- the invented documents

HAZOP_SECTIONS = [
    ("Purpose and scope", "This procedure describes how a HAZOP study is carried out. The scope covers all new "
                          "process units and the objective is to find hazards before start-up."),
    ("Study team", "The study leader chairs the sessions. A scribe records the worksheet. Team members come "
                   "from the process, instrumentation and operations disciplines."),
    ("Preparation", "Before the study the P&IDs and the operating procedures shall be prepared and issued."),
    ("Nodes", "The plant is divided into nodes, each a section with a clear design intent."),
    ("Guidewords", "Guidewords such as no, more and less are applied to each parameter to create deviations."),
    ("Analysis", "For every deviation the causes, the consequences and the safeguards are discussed and noted."),
    ("Risk ranking", "Each consequence is ranked with the risk matrix using severity and likelihood."),
    ("Worksheet", "The worksheet has one row per deviation, with an action column for recommendations."),
    ("Follow-up", "Every recommendation has a responsible person and a due date, and is tracked until closed out."),
    ("Reporting", "A report is issued after the study and the records are retained for the life of the unit."),
    ("Revalidation", "The study is revalidated every five years and after any plant change under management "
                     "of change."),
]


def body_of(sections) -> str:
    out = ""
    for title, text in sections:
        out += d.para(title, style="Heading1") + d.para(text)
    return out


def ingest_docx(tmp_path, sections, name="hazop.docx", **kwargs) -> str:
    path = d.build(tmp_path / name, body_of(sections), **kwargs)
    with open(path, "rb") as fh:
        row, _job, _dup = upload.ingest(fh, name)
    extract.extract_document(row["id"])
    chunker.chunk_document(row["id"])
    with db.connect() as conn:
        conn.execute("UPDATE documents SET status = 'ready' WHERE id = ?", (row["id"],))
    return row["id"]


def hold(identifier: str, name: str | None = None) -> str:
    """Put an invented COMPANY_STANDARD with this designation in the library."""
    doc_id = "std_" + "".join(c for c in identifier.lower() if c.isalnum())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,?,'ready',1,'2026-10-09T00:00:00Z')",
            (doc_id, name or f"{identifier}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf"))
        conn.execute("INSERT INTO document_classification (document_id,suggested_by,document_role,document_number)"
                     " VALUES (?,?,?,?)", (doc_id, "test", "COMPANY_STANDARD", identifier))
    return doc_id


def scope():
    from app.search import every_document_id
    return every_document_id()


def run(doc_id, playbook_id="hazop_procedure", **kw):
    found, _ = playbooks.available()
    return playbooks.review(doc_id, found[playbook_id], allowed_document_ids=scope(), **kw)


def by_id(report):
    return {e["id"]: e for e in report["elements"]}


# ------------------------------------------------------------------- the loader

def valid_data():
    return json.loads((PLAYBOOK_DIR / "hazop_procedure.json").read_text(encoding="utf-8"))


def test_the_two_shipped_playbooks_load_and_every_check_cites_its_clause():
    found, broken = playbooks.available()
    assert broken == [] and set(found) == {"hazop_procedure", "sil_procedure"}
    for pb in found.values():
        assert pb.elements
        for e in pb.elements:
            assert e.standard and e.clause and e.groups, (pb.id, e.id)
    assert {e.standard for e in found["hazop_procedure"].elements} == {"IEC 61882"}
    assert {e.standard for e in found["sil_procedure"].elements} == {"IEC 61511-1"}


def test_the_shipped_playbooks_are_drafts_and_say_their_clauses_are_unchecked():
    found, _ = playbooks.available()
    for pb in found.values():
        assert pb.signed_off is False and pb.sign_off == {"status": "draft", "by": None, "date": None}
        assert pb.clauses_verified is False
        assert "not been signed off" in playbooks.notice(pb) and "DRAFT" in pb.note


def test_a_check_without_a_clause_citation_is_rejected_by_name():
    data = valid_data()
    del data["elements"][2]["source"]["clause"]
    with pytest.raises(playbooks.PlaybookError) as err:
        playbooks.parse(data)
    assert "H03" in str(err.value) and "no clause citation" in str(err.value)
    data = valid_data()
    data["elements"][0]["source"]["standard"] = "  "
    with pytest.raises(playbooks.PlaybookError, match="H01 has no clause citation"):
        playbooks.parse(data)


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.update(format="x"), "format"),
    (lambda d: d.update(elements=[]), "no elements"),
    (lambda d: d["elements"][1].update(id=d["elements"][0]["id"]), "unique id"),
    (lambda d: d["elements"][0].update(evidence=[]), "no evidence cues"),
    (lambda d: d["elements"][0]["evidence"][0].update(any=[]), "no label or no phrases"),
    (lambda d: d["elements"][0].update(title=""), "no title"),
    (lambda d: d.update(sign_off={"status": "maybe"}), "sign_off.status"),
    (lambda d: d.update(sign_off={"status": "signed_off", "by": "A. Engineer"}), "names who signed it"),
])
def test_an_unusable_playbook_is_refused_with_the_reason(mutate, message):
    data = valid_data()
    mutate(data)
    with pytest.raises(playbooks.PlaybookError, match=message):
        playbooks.parse(data)


def test_a_signed_off_playbook_names_who_and_when_and_carries_no_draft_notice():
    data = valid_data()
    data["sign_off"] = {"status": "signed_off", "by": "A. Engineer", "date": "2026-10-09"}
    pb = playbooks.parse(data)
    assert pb.signed_off is True and playbooks.notice(pb) is None


def test_a_broken_playbook_file_is_listed_with_its_reason_never_dropped(tmp_path):
    good = valid_data()
    (tmp_path / "ok.json").write_text(json.dumps(good), encoding="utf-8")
    bad = valid_data()
    bad["id"] = "bad_one"
    del bad["elements"][0]["source"]
    (tmp_path / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
    (tmp_path / "junk.json").write_text("{not json", encoding="utf-8")
    found, broken = playbooks.available(tmp_path)
    assert set(found) == {"hazop_procedure"}
    assert {b["file"] for b in broken} == {"bad.json", "junk.json"}
    assert any("H01 has no clause citation" in b["reason"] for b in broken)


# --------------------------------------------------------------- matching of cues

@pytest.mark.parametrize("cue, text, expected", [
    ("node", "The plant is divided into nodes.", False),           # whole words: "nodes" is not "node"
    ("nodes", "The plant is divided into nodes.", True),
    ("sil", "The silicon layer and the silt trap.", False),
    ("node", "The anode is replaced.", False),                   # nor inside a longer word at its end
    ("sil", "Fossil fuel is stored here", False),
    ("sil", "The SIL of the loop.", True),
    ("revalidat*", "The study is Revalidated yearly.", True),
    ("guide word*", "Guide-words are applied.", True),            # a hyphen or a space in the text
    ("re-hazop", "A re hazop is held.", True),
    ("p&id*", "The P&IDs are issued.", True),
    ("management of change", "Under management  of\nchange rules.", True),
])
def test_cues_match_whole_words_wildcards_and_spacing(cue, text, expected):
    assert bool(playbooks._hits((cue,), text)) is expected


def test_a_quote_is_checked_against_the_passage_ignoring_only_case_and_spacing():
    assert playbooks.quote_in("The  scribe records", "x the scribe\nrecords y")
    assert not playbooks.quote_in("The scribe records everything", "the scribe records")
    assert not playbooks.quote_in("", "anything")


# ----------------------------------------------------------- the review, end to end

def test_a_complete_hazop_procedure_has_every_element_present_with_a_locator_and_a_verbatim_quote(tmp_path):
    hold("IEC 61882")
    doc = ingest_docx(tmp_path, HAZOP_SECTIONS)
    report = run(doc)
    assert report["counts"] == {"present": 11, "unclear": 0, "missing": 0, "could_not_be_checked": 0,
                                "standard_not_held": 0, "total": 11}
    body = " ".join(c["text"] for c in playbooks._chunks(doc))
    for e in report["elements"]:
        assert e["state"] == "present", (e["id"], e["reason"])
        for ev in e["evidence"]:
            assert ev["locator"] and playbooks.quote_in(ev["quote"], body)
    team = by_id(report)["H02"]["evidence"][0]
    assert team["locator"].startswith("2") and "para" in team["locator"]          # heading path > paragraph
    assert report["document"]["read_in_full"] is True
    assert report["playbook"]["signed_off"] is False and report["playbook"]["notice"]


def test_a_part_of_an_element_is_unclear_and_names_what_is_missing(tmp_path):
    hold("IEC 61882")
    sections = [(t, x) for t, x in HAZOP_SECTIONS if t != "Study team"]
    sections.append(("Study team", "The study leader chairs the sessions."))
    report = run(ingest_docx(tmp_path, sections))
    h02 = by_id(report)["H02"]
    assert h02["state"] == "unclear"
    assert h02["missing_cues"] == ["scribe or secretary", "team members or disciplines"]
    assert "no passage mentions scribe or secretary, team members or disciplines" in h02["reason"]
    assert h02["evidence"] and h02["evidence"][0]["locator"]


def test_nothing_found_in_a_document_read_in_full_is_not_found_in_the_pages_read(tmp_path):
    hold("IEC 61882")
    sections = [(t, x) for t, x in HAZOP_SECTIONS if t != "Revalidation"]
    report = run(ingest_docx(tmp_path, sections))
    h11 = by_id(report)["H11"]
    assert h11["state"] == "missing" and h11["reason"] == "not found in the pages read"
    assert report["counts"]["missing"] == 1 and report["counts"]["present"] == 10


def test_a_document_not_read_in_full_cannot_be_called_missing(tmp_path):
    hold("IEC 61882")
    sections = [(t, x) for t, x in HAZOP_SECTIONS if t != "Revalidation"]
    doc = ingest_docx(tmp_path, sections)
    with db.connect() as conn:
        conn.execute("UPDATE documents SET status = 'partially_searchable' WHERE id = ?", (doc,))
    report = run(doc)
    h11 = by_id(report)["H11"]
    assert h11["state"] == "could_not_be_checked"
    assert h11["reason"].startswith("could not be checked: the document is not fully read")
    assert by_id(report)["H01"]["state"] == "present"                 # what WAS found still counts
    assert report["document"]["read_in_full"] is False


def test_pages_that_were_not_read_into_text_make_an_absence_unprovable(tmp_path):
    hold("IEC 61882")
    sections = [(t, x) for t, x in HAZOP_SECTIONS if t != "Revalidation"]
    doc = ingest_docx(tmp_path, sections)
    with db.connect() as conn:
        conn.execute("INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                     " VALUES (?,9,'',0,1,0)", (doc,))
    report = run(doc)
    h11 = by_id(report)["H11"]
    assert h11["state"] == "could_not_be_checked" and "1 page(s) were not read into text" in h11["reason"]
    assert report["document"]["read_in_full"] is False


def test_a_document_with_no_readable_text_is_could_not_be_checked_never_missing(tmp_path):
    hold("IEC 61882")
    doc = ingest_docx(tmp_path, [])
    report = run(doc)
    assert {e["state"] for e in report["elements"]} == {"could_not_be_checked"}
    assert "has no readable text" in report["elements"][0]["reason"]


def test_an_element_whose_standard_is_not_held_is_never_met_even_when_the_text_is_all_there(tmp_path):
    doc = ingest_docx(tmp_path, HAZOP_SECTIONS)              # IEC 61882 is NOT in the library
    report = run(doc)
    assert {e["state"] for e in report["elements"]} == {"standard_not_held"}
    assert report["counts"]["standard_not_held"] == 11 and report["counts"]["present"] == 0
    e = by_id(report)["H02"]
    assert e["standard_held"] is False and e["evidence"] == []
    assert "IEC 61882 is not in the library" in e["reason"] and "not a finding that it is met" in e["reason"]
    assert e["found_at"] and e["found_at"][0]                 # a pointer for the engineer, not a verdict


def test_holding_the_standard_changes_the_same_document_from_not_held_to_present(tmp_path):
    doc = ingest_docx(tmp_path, HAZOP_SECTIONS)
    assert run(doc)["counts"]["present"] == 0
    hold("IEC 61882")
    assert run(doc)["counts"]["present"] == 11


def test_a_sil_procedure_reports_standard_not_held_until_iec_61511_is_in_the_library(tmp_path):
    sil_sections = [
        ("Purpose", "This procedure sets the scope of a SIL assessment under functional safety rules."),
        ("Roles", "The facilitator and the team have the competence for SIL work, with training records."),
        ("Input", "The results of the HAZOP are used as input to the assessment."),
        ("Risk criteria", "The tolerable risk is set by the company risk criteria."),
        ("Method", "The SIL is determined with LOPA, layer of protection analysis."),
        ("Layers", "Each independent protection layer gets a credit, with its PFD."),
        ("SIF", "Every SIF is listed with its target SIL."),
        ("Testing", "The PFD uses the proof test interval of each device."),
        ("Verification", "The assessment is verified by an independent review."),
        ("Records", "A safety requirements specification is produced and records are kept."),
        ("Data", "Failure rate data and the assumptions are stated."),
        ("Change", "The assessment is revalidated under management of change."),
    ]
    doc = ingest_docx(tmp_path, sil_sections, name="sil.docx")
    report = run(doc, "sil_procedure")
    assert report["counts"]["standard_not_held"] == 12 and report["counts"]["present"] == 0
    hold("IEC 61511-1")
    again = run(doc, "sil_procedure")
    assert again["counts"]["present"] == 12 and again["counts"]["standard_not_held"] == 0


def test_a_held_standard_is_matched_by_identity_not_by_a_prefix(tmp_path):
    hold("IEC 615110")                                           # a different standard
    doc = ingest_docx(tmp_path, HAZOP_SECTIONS)
    assert run(doc, "sil_procedure")["counts"]["standard_not_held"] == 12


def test_text_that_is_only_in_a_footer_or_a_deleted_run_is_not_the_documents_content(tmp_path):
    hold("IEC 61882")
    sections = [(t, x) for t, x in HAZOP_SECTIONS if t != "Revalidation"]
    path = d.build(tmp_path / "t.docx", body_of(sections) + d.para("Closing", style="Heading1")
                   + d.para("Nothing more.", deleted="The study is revalidated yearly under management of change."),
                   footer="Revalidation and management of change are covered elsewhere.")
    with open(path, "rb") as fh:
        row, _j, _dup = upload.ingest(fh, "t.docx")
    extract.extract_document(row["id"])
    chunker.chunk_document(row["id"])
    with db.connect() as conn:
        conn.execute("UPDATE documents SET status = 'ready' WHERE id = ?", (row["id"],))
    h11 = by_id(run(row["id"]))["H11"]
    assert h11["state"] == "missing"


def test_a_cue_in_a_heading_path_alone_is_not_enough_to_call_an_element_present(tmp_path):
    hold("IEC 61882")
    sections = [(t, x) for t, x in HAZOP_SECTIONS if t != "Revalidation"]
    sections.append(("Revalidation of the study", "Nothing is said here."))
    h11 = by_id(run(ingest_docx(tmp_path, sections)))["H11"]
    assert h11["state"] == "unclear" and h11["missing_cues"] == ["a statement in the text under the heading"]
    assert h11["evidence"][0]["quote"] is None            # nothing is quoted from a heading


def test_a_pdf_procedure_is_cited_by_page_when_it_has_no_locator(tmp_path):
    hold("IEC 61882")
    pdf = pymupdf.open()
    page = pdf.new_page()
    y = 72
    for _title, text in HAZOP_SECTIONS:
        for line in [text[i:i + 85] for i in range(0, len(text), 85)]:
            page.insert_text((40, y), line, fontsize=8)
            y += 10
    path = tmp_path / "proc.pdf"
    pdf.save(str(path))
    with open(path, "rb") as fh:
        row, _j, _dup = upload.ingest(fh, "proc.pdf")
    extract.extract_document(row["id"])
    chunker.chunk_document(row["id"])
    with db.connect() as conn:
        conn.execute("UPDATE documents SET status = 'ready' WHERE id = ?", (row["id"],))
    report = run(row["id"])
    present = [e for e in report["elements"] if e["state"] == "present"]
    assert present and all(ev["locator"].startswith("page ") for e in present for ev in e["evidence"])


# -------------------------------------------------- a model proposes, code checks

def sparse_doc(tmp_path):
    hold("IEC 61882")
    sections = [(t, x) for t, x in HAZOP_SECTIONS if t != "Revalidation"]
    sections.append(("Reviews", "The team meets again every five years to look at the study once more."))
    return ingest_docx(tmp_path, sections)


def test_a_proposed_quote_that_is_in_the_passage_makes_the_element_present(tmp_path):
    doc = sparse_doc(tmp_path)
    body = playbooks._chunks(doc)
    target = next(i for i, c in enumerate(b for b in body if b["kind"] in playbooks.BODY_KINDS and b["retrievable"])
                  if "meets again" in c["text"])

    def proposer(element, passages):
        return [{"chunk": target, "quote": "meets again every five years"}] if element.id == "H11" else []

    report = run(doc, proposer=proposer)
    h11 = by_id(report)["H11"]
    assert h11["state"] == "present" and h11["evidence"][0]["method"] == "proposed_and_verified"
    assert report["ai"] == {"used": True, "proposed": 1, "kept": 1, "rejected": 0}


def test_a_fabricated_quote_is_rejected_and_counted_and_changes_nothing(tmp_path):
    doc = sparse_doc(tmp_path)

    def proposer(element, passages):
        return [{"chunk": 0, "quote": "The study is revalidated every year"},      # not in passage 0
                {"chunk": 999, "quote": "anything"},                                 # no such passage
                {"chunk": None, "quote": "x"}] if element.id == "H11" else []

    report = run(doc, proposer=proposer)
    assert by_id(report)["H11"]["state"] == "missing"
    assert report["ai"] == {"used": True, "proposed": 3, "kept": 0, "rejected": 3}


def test_no_proposer_means_no_ai_and_the_report_says_so(tmp_path):
    hold("IEC 61882")
    assert run(ingest_docx(tmp_path, HAZOP_SECTIONS))["ai"] == {"used": False, "proposed": 0, "kept": 0, "rejected": 0}


class FakeProvider:
    requested_model = "fake-model"

    def __init__(self, reply):
        self.reply, self.packets = reply, []

    def reason(self, packet):
        self.packets.append(packet)
        text = self.reply(packet) if callable(self.reply) else self.reply
        return Response(text=text, provider="ollama", model_tag="fake-model", digest="d",
                        finish_reason="stop", prompt_sha256=packet.sha256)


def test_the_task_proposer_shows_the_model_a_few_close_passages_and_keeps_only_a_verified_quote(tmp_path):
    doc = sparse_doc(tmp_path)
    provider = FakeProvider(json.dumps({"found": True, "passage": 1, "quote": "meets again every five years"}))
    report = run(doc, proposer=playbooks.task_proposer(provider))
    # only the element the cue words could not settle reaches the model; its prompt is the task runner's
    assert provider.packets and all(p.step == "ai_task:playbook_locate" for p in provider.packets)
    assert all(len(p.prompt.split("TEXT:")[1].split()) <= settings.ai_task_max_words for p in provider.packets)
    h11 = by_id(report)["H11"]
    assert report["ai"]["used"] is True
    assert h11["state"] in ("present", "missing")          # present only if the model chose the right passage
    assert report["ai"]["proposed"] == report["ai"]["kept"] + report["ai"]["rejected"]


def test_a_model_that_invents_a_quote_twice_is_could_not_read_and_proposes_nothing(tmp_path):
    doc = sparse_doc(tmp_path)
    provider = FakeProvider(json.dumps({"found": True, "passage": 1, "quote": "a sentence nobody wrote"}))
    report = run(doc, proposer=playbooks.task_proposer(provider))
    assert report["ai"]["kept"] == 0 and by_id(report)["H11"]["state"] == "missing"
    # the task runner's own check refused the quote, asked once more, and gave up: it never reached the review
    assert report["ai"]["proposed"] == 0 and len(provider.packets) >= 2


def test_a_model_that_says_not_found_leaves_the_cue_word_result_alone(tmp_path):
    doc = sparse_doc(tmp_path)
    provider = FakeProvider(json.dumps({"found": False, "passage": 0, "quote": ""}))
    report = run(doc, proposer=playbooks.task_proposer(provider))
    assert by_id(report)["H11"]["state"] == "missing" and report["ai"]["proposed"] == 0


# ------------------------------------------------------------------------ the API

def test_the_playbook_list_route_shows_sign_off_and_the_draft_notice():
    body = TestClient(app).get("/api/playbooks").json()
    assert {p["id"] for p in body["playbooks"]} == {"hazop_procedure", "sil_procedure"}
    for p in body["playbooks"]:
        assert p["signed_off"] is False and "not been signed off" in p["notice"] and p["elements"] >= 10
    assert body["unusable"] == []


def test_the_review_route_returns_the_report_and_refuses_an_unknown_playbook(tmp_path):
    hold("IEC 61882")
    doc = ingest_docx(tmp_path, HAZOP_SECTIONS)
    client = TestClient(app)
    ok = client.post(f"/api/documents/{doc}/playbook-review", json={"playbook_id": "hazop_procedure"})
    assert ok.status_code == 200 and ok.json()["counts"]["present"] == 11
    bad = client.post(f"/api/documents/{doc}/playbook-review", json={"playbook_id": "nope"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "unknown_playbook"
    gone = client.post("/api/documents/missing/playbook-review", json={"playbook_id": "hazop_procedure"})
    assert gone.status_code == 404


def test_a_caller_who_may_not_read_the_document_cannot_review_it(tmp_path, monkeypatch):
    import secrets
    from app import auth
    monkeypatch.setattr(settings, "auth_secret", secrets.token_urlsafe(48))
    doc = ingest_docx(tmp_path, HAZOP_SECTIONS)
    with db.connect() as conn:
        conn.execute("INSERT INTO users (id,email,display_name,password_hash,is_active,created_at)"
                     " VALUES ('u','u@e.test','U',?,1,'2026-10-09T00:00:00Z')", (auth._hasher.hash("pw-for-test"),))
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(auth.resolve_user_id)
    try:
        client = TestClient(app)
        token = client.post("/api/auth/login", json={"email": "u@e.test", "password": "pw-for-test"}).json()["token"]
        r = client.post(f"/api/documents/{doc}/playbook-review", json={"playbook_id": "hazop_procedure"},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 404
    finally:
        access.set_user_resolver(None)


def test_the_review_route_uses_the_local_model_only_when_asked(tmp_path, monkeypatch):
    hold("IEC 61882")
    doc = ingest_docx(tmp_path, HAZOP_SECTIONS)
    made = []
    monkeypatch.setattr(playbooks, "task_proposer", lambda: made.append(1) or (lambda element, passages: []))
    client = TestClient(app)
    off = client.post(f"/api/documents/{doc}/playbook-review", json={"playbook_id": "hazop_procedure"}).json()
    assert off["ai"]["used"] is False and made == []
    on = client.post(f"/api/documents/{doc}/playbook-review",
                     json={"playbook_id": "hazop_procedure", "use_ai": True}).json()
    assert on["ai"]["used"] is True and made == [1]


# ---------------------------------------------------------------------- the docs

def test_the_playbook_doc_states_the_rules_and_what_is_not_done():
    text = (REPO / "docs" / "playbooks.md").read_text(encoding="utf-8")
    for needle in ("review-playbook/1", "standard not held", "never", "signed off", "not found in the pages read",
                   "hidden", "reserved"):
        assert needle in text.lower() or needle in text, needle
