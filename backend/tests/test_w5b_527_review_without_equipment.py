"""#527 (W5b-03): a review runs on a written document that has no equipment type.

A procedure has no equipment type, so the equipment, service and scope rules
select nothing for it. The review playbook for its kind names the standards
its elements come from; those are mandatory for that kind of document.
INVENTED documents and identifiers only; no client text.

Mutations: M5601-M5610 (scripts/mutations/w5b_527_review_without_equipment.py).
"""
from __future__ import annotations

import dataclasses

import pytest

from app import applicability, db, keyword, playbooks, submittal_review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "app.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    keyword.ensure_schema()
    yield
    db.reset_connection()


def _doc(doc_id: str, filename: str, role: str, text: str = "", kind: str | None = None,
         kind_state: str = "confirmed", **meta) -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',1,'2026-09-18T00:00:00Z')""",
            (doc_id, filename, f"sha-{doc_id}", filename))
        columns = ["document_id", "suggested_by", "document_role", *meta]
        values = [doc_id, "test", role, *meta.values()]
        conn.execute(
            f"INSERT INTO document_classification ({','.join(columns)})"
            f" VALUES ({','.join('?' * len(values))})", values)
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,0,1,1,NULL,'prose',?,1,?,1)""",
            (f"{doc_id}-c1", doc_id, filename, text or filename, f"h-{doc_id}"))
        if kind is not None or kind_state != "confirmed":
            conn.execute("INSERT INTO document_kinds (document_id, kind, state, routed_at)"
                         " VALUES (?,?,?,'2026-09-18T00:00:00Z')", (doc_id, kind, kind_state))
    keyword.index_document(doc_id)
    return doc_id


def _scope(*ids): return frozenset(ids)


# Invented procedure text: a study procedure that cites no standard at all.
HAZOP_TEXT = ("This procedure describes how the HAZOP study is run. The study leader "
              "chairs each session and the scribe keeps the worksheet.")
UNRELATED_TEXT = ("This procedure describes how visitors sign in at the gate and "
                  "collect a badge from reception.")


def _std(doc_id="std_61882", number="IEC 61882"):
    return _doc(doc_id, f"{doc_id}.pdf", "COMPANY_STANDARD", document_number=number)


def _sign_off_all(monkeypatch):
    found, problems = playbooks.available()
    signed = {k: dataclasses.replace(pb, sign_off={**pb.sign_off, "status": "signed_off"})
              for k, pb in found.items()}
    monkeypatch.setattr(playbooks, "available", lambda directory=None: (signed, problems))


def _rows(result):
    return {s["standard_document_id"]: s for s in result["selected"]}


# ------------------------------------------------------------------ selection


def test_a_procedure_with_no_equipment_type_gets_the_playbook_standard(monkeypatch):
    """THE MUTATION TARGET: before #527 nothing was selected for it."""
    _sign_off_all(monkeypatch)
    std = _std()
    sub = _doc("proc", "proc.pdf", "CONTRACTOR_SUBMITTAL", text=HAZOP_TEXT, kind="procedure")
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    row = _rows(result).get(std)
    assert row is not None, "the playbook's mandatory standard was not selected"
    assert row["method"] == applicability.METHOD_PLAYBOOK
    assert row["included"] is True
    assert "HAZOP procedure playbook" in row["reason"] and "procedure" in row["reason"]
    assert "suggested" not in row["reason"]


def test_a_draft_playbook_selects_its_standard_but_does_not_include_it():
    """The shipped playbooks are drafts: considered, never applied on their own."""
    std = _std()
    sub = _doc("proc", "proc.pdf", "CONTRACTOR_SUBMITTAL", text=HAZOP_TEXT, kind="procedure")
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    row = _rows(result)[std]
    assert row["method"] == "playbook_draft"
    assert row["included"] is False
    assert "DRAFT" in applicability.CANDIDATE_ONLY_REASON["playbook_draft"]


def test_a_mandatory_standard_not_held_is_reported_apart_from_missing_citations():
    sub = _doc("proc", "proc.pdf", "CONTRACTOR_SUBMITTAL", text=HAZOP_TEXT, kind="procedure")
    result = applicability.select(sub, allowed_document_ids=_scope(sub), persist=False)
    gaps = {m["identifier"]: m["reason"] for m in result["mandatory_not_held"]}
    assert "IEC 61882" in gaps
    assert "not present in the library" in gaps["IEC 61882"]
    # NEVER worded as a citation: the submittal did not cite it.
    assert result["missing_references"] == []
    assert result["selected"] == []


def test_a_held_mandatory_standard_is_not_reported_as_not_held():
    std = _std()
    sub = _doc("proc", "proc.pdf", "CONTRACTOR_SUBMITTAL", text=HAZOP_TEXT, kind="procedure")
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    assert result["mandatory_not_held"] == []


def test_a_mandatory_standard_also_cited_is_reported_once_as_a_citation():
    sub = _doc("proc", "proc.pdf", "CONTRACTOR_SUBMITTAL",
               text=HAZOP_TEXT + " The study follows IEC 61882.", kind="procedure")
    result = applicability.select(sub, allowed_document_ids=_scope(sub), persist=False)
    assert [m["identifier"] for m in result["missing_references"]] == ["IEC 61882"]
    assert result["mandatory_not_held"] == []


def test_a_procedure_about_something_else_gets_no_playbook_standard():
    """A kind is not enough: every procedure is not a HAZOP procedure."""
    std = _std()
    sub = _doc("proc", "proc.pdf", "CONTRACTOR_SUBMITTAL", text=UNRELATED_TEXT, kind="procedure")
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    assert std not in _rows(result)
    assert result["mandatory_not_held"] == []


def test_a_document_of_another_kind_gets_no_playbook_standard():
    std = _std()
    sub = _doc("proc", "proc.pdf", "CONTRACTOR_SUBMITTAL", text=HAZOP_TEXT, kind="datasheet")
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    assert std not in _rows(result)


def test_a_document_with_no_kind_gets_no_playbook_standard():
    std = _std()
    sub = _doc("proc", "proc.pdf", "CONTRACTOR_SUBMITTAL", text=HAZOP_TEXT)
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    assert std not in _rows(result)
    assert result["mandatory_not_held"] == []


def test_a_kind_the_router_could_not_decide_gets_no_playbook_standard():
    std = _std()
    sub = _doc("proc", "proc.pdf", "CONTRACTOR_SUBMITTAL", text=HAZOP_TEXT,
               kind="procedure", kind_state="needs_engineer")
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    assert std not in _rows(result)


def test_a_suggested_kind_says_it_is_a_guess():
    std = _std()
    sub = _doc("proc", "proc.pdf", "CONTRACTOR_SUBMITTAL", text=HAZOP_TEXT,
               kind="procedure", kind_state="suggested")
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    assert "suggested, not confirmed" in _rows(result)[std]["reason"]
    gaps = applicability.playbook_mandatory(sub, [], HAZOP_TEXT)[1]
    assert all("suggested, not confirmed" in g["reason"] for g in gaps)


def test_a_citation_still_outranks_the_playbook():
    std = _std()
    sub = _doc("proc", "proc.pdf", "CONTRACTOR_SUBMITTAL",
               text=HAZOP_TEXT + " The study follows IEC 61882.", kind="procedure")
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    assert _rows(result)[std]["method"] == applicability.METHOD_REFERENCED


def test_the_text_cue_reads_only_documents_the_caller_may_read():
    """The submittal's text is read under the grants: no grant, no cue, no rule."""
    std = _std()
    sub = _doc("proc", "proc.pdf", "CONTRACTOR_SUBMITTAL", text=HAZOP_TEXT, kind="procedure")
    assert applicability._submittal_text(sub, _scope(std)) == ""
    assert "HAZOP" in applicability._submittal_text(sub, _scope(sub))


def test_a_signed_off_selection_is_written_with_its_method(monkeypatch):
    _sign_off_all(monkeypatch)
    std = _std()
    sub = _doc("proc", "proc.pdf", "CONTRACTOR_SUBMITTAL", text=HAZOP_TEXT, kind="procedure")
    import uuid
    run_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_runs
            (id,submittal_document_id,status,created_at,updated_at)
            VALUES (?,?,'pending','2026-09-18T00:00:00Z','2026-09-18T00:00:00Z')""", (run_id, sub))
    applicability.select(sub, allowed_document_ids=_scope(std, sub), review_run_id=run_id)
    row = db.connect().execute(
        "SELECT selection_method, included FROM review_applicable_standards"
        " WHERE review_run_id = ? AND standard_document_id = ?", (run_id, std)).fetchone()
    assert row["selection_method"] == "playbook" and row["included"] == 1


# ------------------------------------------------------------------ playbook cues


def test_applies_to_needs_a_cue_and_matches_whole_words():
    pb = playbooks.load_file(playbooks.PLAYBOOK_DIR / "sil_procedure.json")
    assert playbooks.applies_to(pb, "The safety integrity levels are set in the study.")
    assert not playbooks.applies_to(pb, "The silage store is cleaned weekly.")
    bare = dataclasses.replace(pb, applies_when=())
    assert not playbooks.applies_to(bare, "safety integrity level")


def test_applies_when_must_be_a_list_of_phrases():
    import json
    data = json.loads((playbooks.PLAYBOOK_DIR / "hazop_procedure.json").read_text(encoding="utf-8"))
    data["applies_when"] = "hazop"
    with pytest.raises(playbooks.PlaybookError, match="applies_when"):
        playbooks.parse(data)
    data["applies_when"] = ["hazop", " "]
    assert playbooks.parse(data).applies_when == ("hazop",)


def test_every_shipped_playbook_has_applies_when_cues():
    found, problems = playbooks.available()
    assert not problems
    assert found and all(pb.applies_when for pb in found.values())
