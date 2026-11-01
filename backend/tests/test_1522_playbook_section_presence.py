"""#1522: a playbook element is present only in its OWN section (invented documents only)."""

from __future__ import annotations

from app.config import settings
from tests.test_w5b_679_playbooks import (  # noqa: F401  (fixtures and helpers)
    HAZOP_SECTIONS,
    by_id,
    hold,
    ingest_docx,
    run,
    temp_storage,
)


def _sections(drop_team: bool):
    out = []
    for title, text in HAZOP_SECTIONS:
        if title == "Study team":
            if drop_team:
                continue
        if title == "Analysis" and drop_team:
            text += " The chairman shall record each deviation, the scribe notes it and the team members agree the wording."
        out.append((title, text))
    return out


def _h02(tmp_path, monkeypatch, *, drop_team, switch):
    monkeypatch.setattr(settings, "playbook_section_presence_enabled", switch)
    hold("IEC 61882")
    return by_id(run(ingest_docx(tmp_path, _sections(drop_team))))["H02"]


def test_a_study_team_section_makes_h02_present(tmp_path, monkeypatch):
    h02 = _h02(tmp_path, monkeypatch, drop_team=False, switch=True)
    assert h02["state"] == "present"


def test_a_passing_mention_in_another_section_is_unclear_with_the_switch_on(
    tmp_path, monkeypatch
):
    h02 = _h02(tmp_path, monkeypatch, drop_team=True, switch=True)
    assert h02["state"] == "unclear" and h02["state"] != "present"
    assert h02["reason"]


def test_the_same_document_is_present_with_the_switch_off(tmp_path, monkeypatch):
    assert (
        _h02(tmp_path, monkeypatch, drop_team=True, switch=False)["state"] == "present"
    )


def test_a_section_heading_match_still_finds_its_evidence(tmp_path, monkeypatch):
    h02 = _h02(tmp_path, monkeypatch, drop_team=False, switch=True)
    assert h02["evidence"] and all(e["quote"] for e in h02["evidence"])
    assert any(
        "chairs" in e["quote"] or "scribe" in e["quote"] for e in h02["evidence"]
    )
