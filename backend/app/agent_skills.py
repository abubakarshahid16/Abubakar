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
MAX_FILE_BYTES = 1_000_000
MAX_ITEMS = 200
MAX_REFS = 30
DEFAULT_DIR = "~/project/mirror/skills"
_TOP = ("kind", "version", "items")
_STR_FIELDS = ("id", "topic", "expected", "acceptable_range", "escalate_when")
_ITEM_FIELDS = (*_STR_FIELDS, "order", "clause_refs")
_REF_FIELDS = ("standard", "clause")
_REPO_ROOT = Path(__file__).resolve().parents[2]


class SkillError(ValueError):
    """A skill file is missing, misplaced or malformed."""


def skills_dir() -> Path:
    return Path(os.environ.get("AGENT_SKILLS_DIR") or DEFAULT_DIR).expanduser()


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _inside_repo(path: Path) -> bool:
    """True when the path is under this repo or under ANY git checkout.

    Compared by file identity (not text), so a different letter case on a
    case-insensitive disk is still caught; and every ancestor holding a `.git`
    entry (another clone or worktree) counts as a repository.
    """
    p = Path(os.path.realpath(path))
    for anc in (p, *p.parents):
        if os.path.lexists(anc / ".git") or _same_file(anc, _REPO_ROOT):
            return True
    return False


def _no_duplicate_keys(pairs: list) -> dict:
    out: dict = {}
    for key, val in pairs:
        if key in out:
            raise SkillError("duplicate key in skill file")
        out[key] = val
    return out


def _check_keys(obj: dict, allowed: tuple, what: str) -> None:
    for key in obj:
        if key not in allowed:
            raise SkillError(f"{what} has an unknown field")


def _check_text(val: object, what: str) -> str:
    if not isinstance(val, str) or not val.strip():
        raise SkillError(f"{what} must be a non-empty string")
    if len(val) > MAX_FIELD_CHARS:
        raise SkillError(f"{what} is longer than {MAX_FIELD_CHARS} characters")
    return val


def _check_refs(refs: object, idx: int) -> None:
    if not isinstance(refs, list):
        raise SkillError(f"item {idx} clause_refs must be a list")
    if len(refs) > MAX_REFS:
        raise SkillError(f"item {idx} has more than {MAX_REFS} clause_refs")
    for ref in refs:
        if not isinstance(ref, dict):
            raise SkillError(f"item {idx} has a bad clause_refs entry")
        _check_keys(ref, _REF_FIELDS, f"item {idx} clause_refs entry")
        for key in _REF_FIELDS:
            if key not in ref:
                raise SkillError(f"item {idx} clause_refs entry missing field: {key}")
            _check_text(ref[key], f"item {idx} clause_refs {key}")


def _check_item(it: object, idx: int) -> None:
    if not isinstance(it, dict):
        raise SkillError(f"item {idx} is not an object")
    for key in _ITEM_FIELDS:
        if key not in it:
            raise SkillError(f"item {idx} missing field: {key}")
    _check_keys(it, _ITEM_FIELDS, f"item {idx}")
    for key in _STR_FIELDS:
        _check_text(it[key], f"item {idx} field {key}")
    if not isinstance(it["order"], int) or isinstance(it["order"], bool):
        raise SkillError(f"item {idx} order must be an integer")
    _check_refs(it["clause_refs"], idx)


def validate_skill(data: object, kind: str | None = None) -> dict:
    if not isinstance(data, dict):
        raise SkillError("skill must be a JSON object")
    for key in _TOP:
        if key not in data:
            raise SkillError(f"missing field: {key}")
    _check_keys(data, _TOP, "skill")
    _check_text(data["kind"], "kind")
    _check_text(data["version"], "version")
    if kind is not None and data["kind"] != kind:
        raise SkillError("skill kind does not match the file")
    items = data["items"]
    if not isinstance(items, list) or not items:
        raise SkillError("items must be a non-empty list")
    if len(items) > MAX_ITEMS:
        raise SkillError(f"more than {MAX_ITEMS} items")
    ids: set[str] = set()
    orders: set[int] = set()
    for idx, it in enumerate(items):
        _check_item(it, idx)
        if it["id"] in ids:
            raise SkillError("duplicate item id")
        if it["order"] in orders:
            raise SkillError("duplicate item order")
        ids.add(it["id"])
        orders.add(it["order"])
    return data


def _read_text(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise SkillError("skill file is too large")
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillError("skill file is not valid UTF-8") from exc
    except OSError as exc:
        raise SkillError("skill file could not be read") from exc


def load_skill(kind: str) -> dict:
    if kind not in KINDS:
        raise SkillError(f"unknown skill kind: {kind}")
    path = skills_dir() / f"{kind}.json"
    if _inside_repo(path):
        raise SkillError("skill files must live outside the git repository")
    if not path.is_file():
        raise SkillError(f"skill file not found for kind {kind}")
    try:
        data = json.loads(_read_text(path), object_pairs_hook=_no_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise SkillError("skill file is not valid JSON") from exc
    return validate_skill(data, kind)


def items_in_order(kind: str, n: int | None = None) -> list[dict]:
    if n is not None and (not isinstance(n, int) or isinstance(n, bool) or n < 0):
        raise SkillError("n must be a whole number of 0 or more")
    items = sorted(load_skill(kind)["items"], key=lambda i: i["order"])
    return items if n is None else items[:n]
