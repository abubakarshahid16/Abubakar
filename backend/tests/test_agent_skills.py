"""Skill loader tests (#1690). Only the made-up sample and tmp dirs are used."""

import copy
import json
from pathlib import Path

import pytest

from app import agent_skills as sk

SAMPLE = Path(__file__).parent / "fixtures" / "sample_skill.json"


def _data():
    return json.loads(SAMPLE.read_text())


def _put(tmp_path, monkeypatch, data, kind="equipment_datasheet"):
    (tmp_path / f"{kind}.json").write_text(json.dumps(data))
    monkeypatch.setenv("AGENT_SKILLS_DIR", str(tmp_path))


def test_loads_sample_from_env_dir(tmp_path, monkeypatch):
    _put(tmp_path, monkeypatch, _data())
    assert sk.load_skill("equipment_datasheet")["version"] == "sample-1"


def test_items_in_order_uses_order_field_and_n(tmp_path, monkeypatch):
    _put(tmp_path, monkeypatch, _data())
    assert [i["id"] for i in sk.items_in_order("equipment_datasheet")] == [
        "W-1",
        "W-2",
        "W-3",
    ]
    assert [i["id"] for i in sk.items_in_order("equipment_datasheet", 2)] == [
        "W-1",
        "W-2",
    ]
    assert sk.items_in_order("equipment_datasheet", 0) == []


def test_rejects_missing_field(tmp_path, monkeypatch):
    d = _data()
    del d["items"][0]["escalate_when"]
    _put(tmp_path, monkeypatch, d)
    with pytest.raises(sk.SkillError, match="missing field"):
        sk.load_skill("equipment_datasheet")


def test_rejects_duplicate_ids(tmp_path, monkeypatch):
    d = _data()
    d["items"][1]["id"] = d["items"][0]["id"]
    _put(tmp_path, monkeypatch, d)
    with pytest.raises(sk.SkillError, match="duplicate"):
        sk.load_skill("equipment_datasheet")


def test_rejects_field_over_600_chars_but_allows_exactly_600(tmp_path, monkeypatch):
    d = copy.deepcopy(_data())
    d["items"][0]["expected"] = "x" * 600
    _put(tmp_path, monkeypatch, d)
    sk.load_skill("equipment_datasheet")
    d["items"][0]["expected"] = "x" * 601
    _put(tmp_path, monkeypatch, d)
    with pytest.raises(sk.SkillError, match="longer than"):
        sk.load_skill("equipment_datasheet")


def test_refuses_skill_inside_repo(monkeypatch):
    repo_dir = Path(sk.__file__).resolve().parents[2] / "backend" / "tests" / "fixtures"
    # the sample sits in the repo under another name; point the loader there
    copy_path = repo_dir / "equipment_datasheet.json"
    assert not copy_path.exists()
    monkeypatch.setenv("AGENT_SKILLS_DIR", str(repo_dir))
    with pytest.raises(sk.SkillError, match="outside the git repository"):
        sk.load_skill("equipment_datasheet")


def test_unknown_kind_and_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SKILLS_DIR", str(tmp_path))
    with pytest.raises(sk.SkillError, match="unknown"):
        sk.load_skill("other")
    with pytest.raises(sk.SkillError, match="not found"):
        sk.load_skill("equipment_datasheet")


def test_kind_must_match_file(tmp_path, monkeypatch):
    d = _data()
    d["kind"] = "hazop_sil_study_procedure"
    _put(tmp_path, monkeypatch, d)
    with pytest.raises(sk.SkillError, match="kind"):
        sk.load_skill("equipment_datasheet")


def test_sample_validates():
    sk.validate_skill(_data(), "equipment_datasheet")


def _fails(tmp_path, monkeypatch, data, match):
    _put(tmp_path, monkeypatch, data)
    with pytest.raises(sk.SkillError, match=match):
        sk.load_skill("equipment_datasheet")


def test_refuses_repo_path_in_other_letter_case(monkeypatch, tmp_path):
    """A case-varied spelling of a path inside the repo (case-insensitive disk)."""
    root = sk._REPO_ROOT
    shouted = Path(str(root).upper())
    if not shouted.exists():
        pytest.skip("case-sensitive disk: a case-varied path does not name the repo")
    monkeypatch.setenv("AGENT_SKILLS_DIR", str(shouted / "BACKEND" / "TESTS"))
    with pytest.raises(sk.SkillError, match="outside the git repository"):
        sk.load_skill("equipment_datasheet")


def test_refuses_dir_under_any_git_checkout(tmp_path, monkeypatch):
    clone = tmp_path / "other_clone"
    (clone / "skills").mkdir(parents=True)
    (clone / ".git").write_text("gitdir: elsewhere")
    (clone / "skills" / "equipment_datasheet.json").write_text(json.dumps(_data()))
    monkeypatch.setenv("AGENT_SKILLS_DIR", str(clone / "skills"))
    with pytest.raises(sk.SkillError, match="outside the git repository"):
        sk.load_skill("equipment_datasheet")


def test_non_utf8_file_is_a_skill_error(tmp_path, monkeypatch):
    (tmp_path / "equipment_datasheet.json").write_bytes(b'{"kind": "\xff\xfe"}')
    monkeypatch.setenv("AGENT_SKILLS_DIR", str(tmp_path))
    with pytest.raises(sk.SkillError, match="UTF-8"):
        sk.load_skill("equipment_datasheet")


def test_duplicate_json_keys_refused(tmp_path, monkeypatch):
    text = json.dumps(_data()).replace(
        '"version": "sample-1"', '"version": "a", "version": "b"'
    )
    (tmp_path / "equipment_datasheet.json").write_text(text)
    monkeypatch.setenv("AGENT_SKILLS_DIR", str(tmp_path))
    with pytest.raises(sk.SkillError, match="duplicate key"):
        sk.load_skill("equipment_datasheet")


def test_duplicate_order_refused(tmp_path, monkeypatch):
    d = _data()
    d["items"][1]["order"] = d["items"][0]["order"]
    _fails(tmp_path, monkeypatch, d, "duplicate item order")


def test_file_size_bound_checked_before_reading(tmp_path, monkeypatch):
    (tmp_path / "equipment_datasheet.json").write_bytes(b" " * (sk.MAX_FILE_BYTES + 1))
    monkeypatch.setenv("AGENT_SKILLS_DIR", str(tmp_path))
    with pytest.raises(sk.SkillError, match="too large"):
        sk.load_skill("equipment_datasheet")


def test_item_count_and_refs_bounds(tmp_path, monkeypatch):
    d = _data()
    d["items"] = [
        {**d["items"][0], "id": f"X{i}", "order": i} for i in range(sk.MAX_ITEMS + 1)
    ]
    _fails(tmp_path, monkeypatch, d, "more than")
    d = _data()
    d["items"][0]["clause_refs"] = [
        {"standard": "S", "clause": str(i)} for i in range(sk.MAX_REFS + 1)
    ]
    _fails(tmp_path, monkeypatch, d, "clause_refs")


def test_unknown_fields_refused_at_every_level(tmp_path, monkeypatch):
    d = _data()
    d["extra"] = "x"
    _fails(tmp_path, monkeypatch, d, "unknown field")
    d = _data()
    d["items"][0]["note"] = "x"
    _fails(tmp_path, monkeypatch, d, "unknown field")
    d = _data()
    d["items"][0]["clause_refs"] = [{"standard": "S", "clause": "1", "text": "x"}]
    _fails(tmp_path, monkeypatch, d, "unknown field")


def test_every_string_is_length_limited(tmp_path, monkeypatch):
    d = _data()
    d["version"] = "v" * 601
    _fails(tmp_path, monkeypatch, d, "longer than")
    d = _data()
    d["items"][0]["clause_refs"] = [{"standard": "S", "clause": "c" * 601}]
    _fails(tmp_path, monkeypatch, d, "longer than")


@pytest.mark.parametrize("bad", [-1, "3", 1.5, True])
def test_items_in_order_validates_n(tmp_path, monkeypatch, bad):
    _put(tmp_path, monkeypatch, _data())
    with pytest.raises(sk.SkillError, match="whole number"):
        sk.items_in_order("equipment_datasheet", bad)
