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
