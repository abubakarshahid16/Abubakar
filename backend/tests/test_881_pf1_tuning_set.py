"""PF1 (#881): the committed invented TUNING set.

`backend/tests/fixtures/synthetic/pf1/` holds the only PF1 sheets that may be
in git (planner option (a)): invented, not held out, no library group. Its
spec sits beside it. These tests keep it honest: the committed bytes are what
the committed spec builds (so nobody hand-edits a key), every document is
tuning and invented, and the files the GitHub CPU workflow may read are plain
names inside the folder.
"""

from __future__ import annotations

import json
from pathlib import Path

from tools import pf1_set, review_score

SET = Path(__file__).resolve().parent / "fixtures" / "synthetic" / "pf1"


def _spec() -> dict:
    return json.loads((SET / "spec.json").read_text(encoding="utf-8"))


def test_the_committed_files_are_exactly_what_the_committed_spec_builds(tmp_path):
    pf1_set.build(_spec(), tmp_path / "fresh")
    fresh = {p.name: p.read_bytes() for p in (tmp_path / "fresh").iterdir()}
    committed = {p.name: p.read_bytes() for p in SET.iterdir() if p.name != "spec.json"}
    assert fresh == committed


def test_every_committed_document_is_invented_tuning_and_has_no_library_standard():
    index = json.loads((SET / "index.json").read_text(encoding="utf-8"))
    assert index["source"] == "invented" and len(index["documents"]) >= 4
    for entry in index["documents"]:
        assert entry["held_out"] is False and entry["group"] == "invented"
        assert entry["library_standards"] == 0 and entry["standard"]
        for name in (entry["datasheet"], entry["standard"], entry["key"]):
            assert Path(name).name == name and (SET / name).is_file()


def test_the_keys_are_valid_and_each_document_has_a_defect_and_a_correct_item():
    for key_file in SET.glob("*.key.json"):
        key = review_score.load_key(key_file)
        kinds = {item["kind"] for item in key["items"]}
        assert (
            key["source"] == "invented"
            and "defect" in kinds
            and kinds & {"met", "trap"}
        )


def test_the_set_covers_several_types_and_layouts():
    index = json.loads((SET / "index.json").read_text(encoding="utf-8"))
    assert len({d["equipment_type"] for d in index["documents"]}) >= 4
    assert len({d["layout"] for d in index["documents"]}) >= 4
