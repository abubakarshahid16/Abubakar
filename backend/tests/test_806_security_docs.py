"""#806 S1-S12: the security controls pack is committed, and the AI register
matches the AI switches in config.py by name and default (S2: "a CI test
fails if a model switch in config.py is not listed").
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("check_ai_register", ROOT / "scripts" / "check_ai_register.py")
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def test_the_pack_is_complete_and_the_register_matches_the_code():
    assert check.problems() == []


def test_every_control_file_names_its_question():
    for name in check.CONTROL_FILES[1:]:
        text = (check.DOCS / name).read_text(encoding="utf-8")
        assert text.startswith("# S") and "(Q" in text.splitlines()[0], name


def test_a_switch_missing_from_the_register_fails(monkeypatch):
    actual = check.config_switches()
    monkeypatch.setattr(check, "config_switches", lambda: {**actual, "new_ai_step_enabled": "True"})
    assert check.problems() == ["AI switch not in the register: new_ai_step_enabled (default True)"]


def test_a_changed_default_fails(monkeypatch):
    actual = check.config_switches()
    flipped = {**actual, "crs_ai_wording_enabled": "False"}
    monkeypatch.setattr(check, "config_switches", lambda: flipped)
    assert check.problems() == [
        "default differs for crs_ai_wording_enabled: config.py False, register True"]


def test_a_switch_the_code_no_longer_has_fails(monkeypatch):
    actual = dict(check.config_switches())
    actual.pop("answer_judge_enabled")
    monkeypatch.setattr(check, "config_switches", lambda: actual)
    assert check.problems() == ["register lists a switch config.py does not have: answer_judge_enabled"]


def test_the_switch_rule_finds_the_known_ai_switches():
    names = set(check.config_switches())
    assert {"reasoning_provider", "datasheet_ai_reader", "match_enabled",
            "review_ai_check_enabled", "crs_ai_wording_enabled"} <= names
    assert "market_live_enabled" not in names and "auth_mode" not in names


def test_an_engine_selector_is_a_switch_but_a_model_name_is_not():
    """#794 adds `match_engine` (local model or Claude API): choosing the
    engine is an AI switch, so a new one cannot skip the register."""
    assert check.is_switch("match_engine", str)
    assert check.is_switch("datasheet_ai_reader", str) and check.is_switch("match_enabled", bool)
    assert not check.is_switch("answer_model", str)        # which model, not which engine
    assert not check.is_switch("vector_backend", str)      # not an AI step
    assert not check.is_switch("match_engine", bool)


def test_the_pack_carries_no_secret_shaped_text():
    import re
    for path in check.DOCS.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"sk-ant-[A-Za-z0-9]|ghp_[A-Za-z0-9]{20}|github_pat_", text), path.name


def test_the_owner_signoff_page_exists_names_each_owner_issue_and_its_links_resolve():
    import re

    page = check.DOCS / "owner-signoff.md"
    text = page.read_text(encoding="utf-8")
    for issue in ("#817", "#820", "#821", "#825", "#826"):
        assert issue in text, issue
    links = re.findall(r"\]\(([^)#]+\.md)\)", text)
    assert links, "the page links no control file"
    for link in links:
        assert (check.DOCS / link).is_file(), link
    assert "owner-signoff.md" in (check.DOCS / "README.md").read_text(encoding="utf-8")
