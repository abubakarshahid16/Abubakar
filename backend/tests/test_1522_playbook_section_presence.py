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
            title = "Study team members"
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


def _element():
    from app import playbooks

    found, _ = playbooks.available()
    return next(e for e in found["hazop_procedure"].elements if e.id == "H02")


def _chunk(section, context, text):
    return {
        "section": section,
        "context": context,
        "text": section + "\n" + text,
        "locator": "p1",
        "page_start": 1,
    }


CHAIRMAN = "The chairman shall record each deviation, the scribe notes it and the team members agree."


def test_a_parent_or_document_heading_does_not_make_a_methodology_paragraph_the_team_section(
    monkeypatch,
):
    from app import playbooks

    monkeypatch.setattr(settings, "playbook_section_presence_enabled", True)
    body = [
        _chunk("Methodology", "Study team members procedure > Methodology", CHAIRMAN)
    ]
    assert playbooks._match(_element(), body)["state"] == "unclear"


def test_a_nearest_heading_naming_the_team_makes_it_present(monkeypatch):
    from app import playbooks

    monkeypatch.setattr(settings, "playbook_section_presence_enabled", True)
    body = [
        _chunk(
            "Study team members", "HAZOP Study Procedure > Study team members", CHAIRMAN
        )
    ]
    assert playbooks._match(_element(), body)["state"] == "present"


def test_with_the_switch_off_the_evidence_is_the_old_dict(monkeypatch):
    from app import playbooks

    monkeypatch.setattr(settings, "playbook_section_presence_enabled", False)
    body = [
        _chunk("Methodology", "Study team members procedure > Methodology", CHAIRMAN)
    ]
    found = playbooks._match(_element(), body)
    assert found["state"] == "present"
    assert found["evidence"] == [
        {
            "locator": "p1",
            "quote": found["evidence"][0]["quote"],
            "method": "cue_words",
            "groups": [
                "study leader",
                "scribe or secretary",
                "team members or disciplines",
            ],
            "in_text": True,
        }
    ]


def test_known_limit_a_heading_without_an_element_cue_is_unclear_not_present(
    monkeypatch,
):
    from app import playbooks

    monkeypatch.setattr(settings, "playbook_section_presence_enabled", True)
    for heading in ("Study Team", "Team and roles"):
        body = [_chunk(heading, "HAZOP Study Procedure > " + heading, CHAIRMAN)]
        assert playbooks._match(_element(), body)["state"] == "unclear", heading


def test_a_definitions_entry_is_not_the_team_section(monkeypatch):
    from app import playbooks

    monkeypatch.setattr(settings, "playbook_section_presence_enabled", True)
    for entry in ("Chairman", "Team members", "Scribe"):
        body = [_chunk(entry, "Procedure > 2. Definitions > " + entry, CHAIRMAN)]
        assert playbooks._match(_element(), body)["state"] == "unclear", entry
    body = [_chunk("Abbreviations and definitions", "Procedure", CHAIRMAN)]
    assert playbooks._match(_element(), body)["state"] == "unclear"


def test_a_report_contents_list_item_is_not_the_team_section(monkeypatch):
    from app import playbooks

    monkeypatch.setattr(settings, "playbook_section_presence_enabled", True)
    body = [_chunk("Team members", "Procedure > Report contents > Team members", CHAIRMAN)]
    assert playbooks._match(_element(), body)["state"] == "unclear"
    body = [_chunk("Table of contents", "Procedure", CHAIRMAN)]
    assert playbooks._match(_element(), body)["state"] == "unclear"


def test_a_real_team_section_under_a_numbered_parent_is_still_present(monkeypatch):
    from app import playbooks

    monkeypatch.setattr(settings, "playbook_section_presence_enabled", True)
    body = [_chunk("HAZOP team members", "Procedure > 4. Study > HAZOP team members", CHAIRMAN)]
    assert playbooks._match(_element(), body)["state"] == "present"


def test_a_definitions_entry_is_still_present_with_the_switch_off(monkeypatch):
    from app import playbooks

    monkeypatch.setattr(settings, "playbook_section_presence_enabled", False)
    body = [_chunk("Chairman", "Procedure > 2. Definitions > Chairman", CHAIRMAN)]
    assert playbooks._match(_element(), body)["state"] == "present"
