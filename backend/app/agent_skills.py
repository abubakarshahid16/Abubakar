"""Skill loader for the agent review (#1690, part of #805).

A skill is a playbook for one document kind: per item the expected position,
the acceptable range and what triggers escalation to the engineer, with clause
references. Skill CONTENT is local only (default ~/project/mirror/skills, or
AGENT_SKILLS_DIR) and is never committed: the loader refuses a skill file that
lives inside this git repository, and refuses any item field longer than
MAX_FIELD_CHARS, so skills stay playbooks and cannot hold copied standard text.
No skill text is logged.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

KINDS = ("equipment_datasheet", "hazop_sil_study_procedure")
MAX_FIELD_CHARS = 600
DEFAULT_DIR = "~/project/mirror/skills"
_TOP = ("kind", "version", "items")
_STR_FIELDS = ("id", "topic", "expected", "acceptable_range", "escalate_when")
_REPO_ROOT = Path(__file__).resolve().parents[2]


class SkillError(ValueError):
    """A skill file is missing, misplaced or malformed."""


def skills_dir() -> Path:
    return Path(os.environ.get("AGENT_SKILLS_DIR") or DEFAULT_DIR).expanduser()


def _inside_repo(path: Path) -> bool:
    p = path.resolve()
    return p == _REPO_ROOT or _REPO_ROOT in p.parents


def validate_skill(data: object, kind: str | None = None) -> dict:
    if not isinstance(data, dict):
        raise SkillError("skill must be a JSON object")
    for key in _TOP:
        if key not in data:
            raise SkillError(f"missing field: {key}")
    if kind is not None and data["kind"] != kind:
        raise SkillError("skill kind does not match the file")
    items = data["items"]
    if not isinstance(items, list) or not items:
        raise SkillError("items must be a non-empty list")
    seen: set[str] = set()
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            raise SkillError(f"item {idx} is not an object")
        for key in (*_STR_FIELDS, "order", "clause_refs"):
            if key not in it:
                raise SkillError(f"item {idx} missing field: {key}")
        for key in _STR_FIELDS:
            val = it[key]
            if not isinstance(val, str) or not val.strip():
                raise SkillError(f"item {idx} field {key} must be a non-empty string")
            if len(val) > MAX_FIELD_CHARS:
                raise SkillError(
                    f"item {idx} field {key} is longer than {MAX_FIELD_CHARS} characters"
                )
        if not isinstance(it["order"], int) or isinstance(it["order"], bool):
            raise SkillError(f"item {idx} order must be an integer")
        refs = it["clause_refs"]
        if not isinstance(refs, list):
            raise SkillError(f"item {idx} clause_refs must be a list")
        for ref in refs:
            if not isinstance(ref, dict) or not all(
                isinstance(ref.get(k), str)
                and ref.get(k)
                and len(ref[k]) <= MAX_FIELD_CHARS
                for k in ("standard", "clause")
            ):
                raise SkillError(f"item {idx} has a bad clause_refs entry")
        if it["id"] in seen:
            raise SkillError("duplicate item id")
        seen.add(it["id"])
    return data


def load_skill(kind: str) -> dict:
    if kind not in KINDS:
        raise SkillError(f"unknown skill kind: {kind}")
    path = skills_dir() / f"{kind}.json"
    if _inside_repo(path):
        raise SkillError("skill files must live outside the git repository")
    if not path.is_file():
        raise SkillError(f"skill file not found for kind {kind}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SkillError("skill file is not valid JSON") from exc
    return validate_skill(data, kind)


def items_in_order(kind: str, n: int | None = None) -> list[dict]:
    items = sorted(load_skill(kind)["items"], key=lambda i: i["order"])
    return items if n is None else items[: max(0, n)]
