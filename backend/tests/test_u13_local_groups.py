"""Update 13 (lead-4, 26 Nov 2026 16:03): the client's own document groups live in a LOCAL file in the data folder
(`document_groups.local.json`, git-ignored), never in the public repository. When present it adds its groups to the repository table
(which keeps the six families and invented examples only); without it the app works on the repository table alone. Invented groups only."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app import document_groups as DG
from app import kind_list
from app.config import settings

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    DG._load.cache_clear()
    yield tmp_path
    DG._load.cache_clear()


def _local(folder: Path, groups: dict) -> Path:
    p = folder / DG.LOCAL_NAME
    p.write_text(json.dumps({"groups": groups}), encoding="utf-8")
    DG._load.cache_clear()
    return p


INVENTED = {
    "g01": {
        "label": "Invented widget register",
        "family": "list_register",
        "kind": None,
        "words": ["invented widget register"],
    },
    "g02": {
        "label": "Invented gizmo sizing note",
        "family": "study_calculation",
        "kind": "calculation",
        "words": ["invented gizmo sizing note"],
    },
}


def test_without_the_local_file_the_app_works_on_the_repository_table_alone(data):
    t = DG.table()
    assert (
        t["local_groups"] == []
        and DG.place("other", ["invented widget register"]).how != "group"
    )


def test_the_repository_keeps_invented_examples_only_one_group_per_listed_kind(data):
    repo = json.loads(DG.PATH.read_text(encoding="utf-8"))["groups"]
    assert set(repo) == set(kind_list.kinds()) and all(
        row["kind"] == g for g, row in repo.items()
    )


def test_the_local_file_adds_its_groups_and_a_paper_is_placed_by_them(data):
    _local(data, INVENTED)
    t = DG.table()
    assert t["local_groups"] == ["g01", "g02"] and set(t["groups"]) >= set(
        kind_list.kinds()
    ) | {"g01", "g02"}
    p = DG.place("other", ["an invented widget register of the plant"])
    assert (p.how, p.group, p.family) == ("group", "g01", "list_register")


def test_a_changed_local_file_is_read_again(data):
    p = _local(data, INVENTED)
    assert len(DG.table()["local_groups"]) == 2
    p.write_text(json.dumps({"groups": {"g01": INVENTED["g01"]}}), encoding="utf-8")
    import os

    os.utime(
        p, (p.stat().st_atime, p.stat().st_mtime + 5)
    )  # a later write, as a real edit would be
    assert DG.table()["local_groups"] == ["g01"]


@pytest.mark.parametrize(
    "groups",
    [
        {"datasheet": INVENTED["g01"]},  # reuses a repository id
        {"g01": {**INVENTED["g01"], "family": "nonsense"}},
        {"g01": {**INVENTED["g01"], "words": ["Upper Case"]}},
        {"g01": {**INVENTED["g01"], "kind": "nonsense"}},
        {},
    ],
)
def test_a_bad_local_file_is_refused_never_half_used(data, groups):
    _local(data, groups)
    with pytest.raises(DG.DocumentGroupsError):
        DG.table()


def test_the_local_file_is_git_ignored_and_never_tracked():
    if shutil.which("git") is None or not (REPO_ROOT / ".git").exists():
        pytest.skip("no git checkout here")
    rel = f"backend/data/{DG.LOCAL_NAME}"
    ignored = subprocess.run(["git", "check-ignore", "-q", rel], cwd=REPO_ROOT)
    assert ignored.returncode == 0, "the local groups file must be git-ignored"
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", rel], cwd=REPO_ROOT, capture_output=True
    )
    assert tracked.returncode != 0, "the local groups file must never be tracked"
    assert not any(
        p.name == DG.LOCAL_NAME for p in REPO_ROOT.glob("backend/app/**/*.json")
    )
