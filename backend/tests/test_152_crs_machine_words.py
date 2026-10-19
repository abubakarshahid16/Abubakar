"""Order 152.2: no machine wording in the contractor's copy. Invented data
only - no client, document or datasheet text.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import crs_issue, datasheet_checks, main
from app import crs_machine_words as mw
from app.config import settings
from tests.test_885_crs_issue_gate import _run as _run885
from tests.test_crs_endpoint import _client, _submittal, temp_db  # noqa: F401

COVERED = {"pages_total": 1, "pages_not_read_into_fields": []}
CODE = next(k for k in sorted(datasheet_checks.load_rules()["roles"]) if "_" in k)


def _row(n: int, comment: str, **over) -> dict:
    return {
        "finding_id": f"f{n}",
        "document_name": "inv.pdf",
        "page_section": f"p.{n}",
        "comment": comment,
        "comment_by": "AI Review",
        "row_kind": "missing_information",
        "engineer_confirmed": True,
        **over,
    }


# ------------------------------------------------------------ the words


@pytest.mark.parametrize(
    "text, word",
    [
        (f"The {CODE} is not stated.", CODE),
        ("Shown as doc_a3df49861559 cl. 4.", "doc_a3df49861559"),
        ("Shown as doc_93df49861559 cl. 4.", "doc_93df49861559"),  # a digit first
        ("Linked through the synonym table as 'x'.", "synonym table"),
        ("Paired by a containment match.", "containment match"),
        ("Written by a Language Model.", "Language Model"),
    ],
)
def test_machine_words_are_found(text, word):
    assert word in mw.find_machine_words(text)


def test_model_ids_and_engine_names_come_from_the_settings(monkeypatch):
    monkeypatch.setattr(settings, "answer_model", "zorbex9:77b")
    found = mw.find_machine_words("Worded by zorbex9:77b, then checked by Ollama.")
    assert "zorbex9:77b" in found and "Ollama" in found


def test_quoted_document_text_and_ordinary_words_are_clean():
    plain = (
        "Tags HV_A and PT_A1 per ASME_B31.3, see Fig.A(1), product proMax. "
        "Contact Claude Dupont. The embedding length of anchor bolts is 300 mm, "
        "secondary containment applies, the matcher plate is stamped. "
        "Design pressure 12 bar; 15 kWh/d; 120 mmHg; doc_xyz and doc_12345 are labels."
    )
    assert mw.find_machine_words(plain) == []
    assert mw.find_machine_words(None) == [] and mw.find_machine_words("  ") == []


def test_the_stored_id_shape_is_the_one_upload_writes():
    source = (Path(mw.__file__).parent / "upload.py").read_text()
    assert 'f"doc_{sha256[:12]}"' in source
    assert re.fullmatch(mw.DOC_ID.pattern, "doc_" + "0123456789ab")


# ------------------------------------------------------- which cells count


def test_scan_reports_comment_number_cell_and_words():
    rows = [
        _row(1, "Plain words only."),
        _row(2, f"Field {CODE} missing.", crs_ref="CRS-001-002"),
        _row(3, "Fine.", standard_reference="doc_0123456789ab cl. 4"),
    ]
    assert mw.scan_issue_rows(rows) == [
        {"comment": "CRS-001-002", "cell": "comment", "words": [CODE]},
        {"comment": "3", "cell": "standard_reference", "words": ["doc_0123456789ab"]},
    ]


def test_engineers_own_comment_text_is_not_scanned():
    bad = f"my note about {CODE}, the embedding, a language model"
    rows = [
        _row(1, bad, edited=True),
        _row(2, bad, row_kind="engineer_comment"),
        _row(3, bad, row_kind="ai_engineering_check", engineer_worded=True),
        _row(4, bad, row_kind="carried_forward"),
    ]
    assert mw.scan_issue_rows(rows) == []
    # ... but the same words in a machine-written comment are found
    assert mw.scan_issue_rows([_row(5, bad)])


def test_chat_row_with_an_ordinary_word_is_not_blocked():
    row = _row(1, "The embedding length is short.", row_kind="engineer_comment")
    assert mw.scan_issue_rows([row]) == []


def test_page_section_and_standard_reference_are_scanned_even_for_engineer_rows():
    for cell in ("page_section", "standard_reference"):
        row = _row(1, "mine", edited=True, **{cell: f"{CODE} p.2"})
        (hit,) = mw.scan_issue_rows([row])
        assert hit["cell"] == cell and hit["words"] == [CODE]


def test_rows_the_issue_copy_does_not_carry_are_not_scanned():
    bad = CODE
    rows = [
        _row(1, bad, engineer_confirmed=False),
        _row(2, bad, engineer_rejected=True),
        _row(3, bad, row_kind="safety_tick"),
        _row(4, bad, ai_review_comment="a draft"),
    ]
    assert mw.scan_issue_rows(rows) == []


# ------------------------------------------------------------- the gate


def test_gate_names_the_cell_the_comment_and_the_remedy():
    rows = [
        _row(1, "Plain."),
        _row(2, f"Field {CODE} is missing."),
        _row(3, "Fine.", standard_reference="doc_0123456789ab cl. 4"),
        _row(4, "Fine.", page_section=f"p.1 {CODE}"),
    ]
    gate = crs_issue.open_items("run-1", rows, COVERED)
    assert gate["issuable"] is False
    comment, std, cell = gate["blockers"]
    assert comment.startswith("Comment of comment(s) 2") and CODE in comment
    assert "edit its wording" in comment
    assert "Standard reference of comment(s) 3" in std and "no readable name" in std
    assert "Page and section of comment(s) 4" in cell and "correct the item" in cell


def test_gate_is_open_for_plain_words():
    gate = crs_issue.open_items("run-1", [_row(1, "Plain.")], COVERED)
    assert gate["blockers"] == [] and gate["issuable"] is True


def test_names_are_read_once_per_scan(monkeypatch):
    calls = []
    real = mw.Names

    def counted():
        calls.append(1)
        return real()

    monkeypatch.setattr(mw, "Names", counted)
    mw.scan_issue_rows([_row(i, "Plain.") for i in range(5)])
    assert len(calls) == 1


# ------------------------------------------------------ the HTTP issue path


def test_issue_route_answers_409_with_the_blocker_for_a_machine_word(monkeypatch):
    doc = _submittal()
    run = _run885(doc)  # final code recorded, every page read
    rows = [_row(1, f"The {CODE} is wrong.", crs_row_key="k1")]
    real = main._crs_content
    monkeypatch.setattr(
        main,
        "_crs_content",
        lambda rid, scope, copy="internal": (rows, *real(rid, scope, copy)[1:]),
    )
    client = _client(doc)
    r = client.post(f"/api/reviews/runs/{run}/crs/issue")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "crs_not_finished"
    assert (
        f"Comment of comment(s) 1 holds wording only the program uses ('{CODE}')"
        in (r.json()["detail"]["message"])
    )
    # plain words: the same route issues it
    rows[0]["comment"] = "The design value is wrong."
    assert client.post(f"/api/reviews/runs/{run}/crs/issue").status_code == 200
