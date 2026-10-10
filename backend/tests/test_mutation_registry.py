"""The mutation registry: one file per mutated module, ids globally unique.

`scripts/mutation_check.py` used to hold every entry itself; they now live in
`scripts/mutations/<module>.py` and the harness concatenates them. Splitting a
list across forty files makes a duplicate id invisible to a reader, so the
harness refuses one at import - and these tests hold it to that.

Mutation: M576 (`python scripts/mutation_check.py --only M576`) deletes the
duplicate check; `test_a_duplicate_id_across_two_modules_is_refused` fails.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import mutation_check  # noqa: E402


def test_the_registry_loads_every_module_and_ids_are_unique():
    modules = mutation_check.registry_modules()
    # Not vacuous: the split produced 40 files and 515 entries; an empty
    # package or a loader that found nothing would pass a uniqueness check.
    assert len(modules) >= 40, modules
    assert len(mutation_check.ALL) >= 515
    ids = [m.id for m in mutation_check.ALL]
    assert len(ids) == len(set(ids))
    for name in modules:
        entries = __import__(f"mutations.{name}", fromlist=["MUTATIONS"]).MUTATIONS
        assert entries, f"mutations.{name} defines no MUTATIONS"


def test_every_entry_edits_a_file_that_exists():
    missing = [(m.id, str(m.path)) for m in mutation_check.ALL if not m.path.is_file()]
    assert missing == []


def test_a_duplicate_id_across_two_modules_is_refused():
    first = mutation_check.ALL[0]
    clash = dataclasses.replace(first, description="another mutation, same id")
    other = dataclasses.replace(first, id=first.id + "_distinct")
    # Two distinct ids are accepted, so the refusal below is about the id.
    assert len(mutation_check.aggregate([("alpha", (first,)), ("beta", (other,))])) == 2
    with pytest.raises(ValueError, match=rf"duplicate mutation id '{first.id}'.*alpha.*beta"):
        mutation_check.aggregate([("alpha", (first,)), ("beta", (clash,))])


def test_ids_named_after_their_pr_are_accepted_and_still_unique():
    """CLAUDE.md rule 12 (#749): ids are `M<PR>-NN` with `phase=<PR>`, so two
    PRs never pick the same "next free number". The registry must take that
    shape as it takes `M576`, and still refuse the same id twice."""
    base = mutation_check.ALL[0]
    one = dataclasses.replace(base, id="M746-01", phase=746)
    two = dataclasses.replace(base, id="M746-02", phase=746)
    other_pr = dataclasses.replace(base, id="M747-01", phase=747)
    merged = mutation_check.aggregate([("a", (one, two)), ("b", (other_pr,))])
    assert [m.id for m in merged] == ["M746-01", "M746-02", "M747-01"]
    assert {m.phase for m in merged} == {746, 747}
    with pytest.raises(ValueError, match=r"duplicate mutation id 'M746-01'"):
        mutation_check.aggregate([("a", (one,)), ("b", (dataclasses.replace(one, description="again"),))])


def test_the_mutation_backup_is_outside_the_repo_and_the_file_is_restored(tmp_path, monkeypatch):
    """A `.mutbak` next to the source was once committed mid-run, with the
    mutated file. The backup now lives in a temp directory."""
    target = tmp_path / "victim.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    mutation = mutation_check.Mutation(
        id="MTEST", phase=1, description="d", path=target, anchor="VALUE = 1",
        replacement="VALUE = 2", target="tests/x.py")
    seen = {}

    def fake_run_tests(_m):
        seen["siblings"] = sorted(p.name for p in tmp_path.iterdir())
        seen["text_during"] = target.read_text(encoding="utf-8")
        return 1, "1 failed"

    monkeypatch.setattr(mutation_check, "_run_tests", fake_run_tests)
    monkeypatch.setattr(mutation_check, "_tests_collected", lambda *_a: 1)
    verdict, _ = mutation_check.run(mutation)
    assert verdict == "DETECTED"
    assert seen["text_during"] == "VALUE = 2\n"
    assert seen["siblings"] == ["victim.py"]            # no .mutbak beside the source
    assert target.read_text(encoding="utf-8") == "VALUE = 1\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["victim.py"]


def test_gitignore_keeps_a_mutation_backup_out_of_a_commit():
    lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "*.mutbak" in lines
