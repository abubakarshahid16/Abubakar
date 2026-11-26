"""THE ONE KIND LIST (planner 25 Nov 2026, item 1): every kind is named in `reference/kind_list.json`, each in one review family; the
sorter's cues, the engine's table, the paper-kind reading, the sentence nouns and the picker all read it, and a kind that is not scored
keeps its unscored behaviour. Invented values only; no model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import (
    doc_router,
    document_kind,
    kind_list,
    kind_review_table,
    kind_words,
    paper_kind,
)
from app.aim_review_measured import _table as measured_table

REF = Path(kind_list.__file__).parent / "reference"
FAMILIES = {
    "written_document",
    "study_calculation",
    "drawing_diagram",
    "list_register",
    "certificate_record",
    "datasheet",
}


def test_every_kind_has_a_label_a_noun_and_one_of_the_six_families():
    assert set(kind_list.families()) == FAMILIES
    for name, row in kind_list.kinds().items():
        assert row["label"] and row["noun"] and row["family"] in FAMILIES, name


def test_no_other_file_names_a_kind_the_list_does_not_hold():
    sorter = json.loads((REF / "document_kinds.json").read_text())["kinds"].keys()
    engine = json.loads((REF / "kind_review_table.json").read_text())["kinds"].keys()
    assert kind_list.problems(sorter, engine) == []


def test_the_measured_scores_name_only_kinds_on_the_list():
    for name in measured_table().get("kinds", {}):
        assert name in kind_list.kinds() or name in {"study"}, (
            name
        )  # the measured table's "study" is the list's study


def test_the_sorter_the_picker_the_paper_kind_and_the_nouns_read_the_list():
    assert tuple(k["id"] for k in doc_router.kinds()) == kind_list.confirmable_kinds(
        with_switch_kinds=False
    )
    assert set(paper_kind.PAPER_KINDS) == {
        *(k for k, r in kind_list.kinds().items() if r["code_decided"]),
        "other",
    }
    assert set(kind_words.NOUNS) == {
        k for k, r in kind_list.kinds().items() if r["code_decided"]
    }
    assert all(
        k["family"] in FAMILIES and k["label"] for k in doc_router.kinds()
    )  # the picker shows the family too


def test_the_family_never_makes_a_kind_reviewable_or_scored():
    """A family says how a kind is laid out; whether it is reviewed and scored stays the engine table's word (unscored = Automatic
    does not send it)."""
    for kind in ("report", "letter", "study", "feed", "standard"):
        assert kind_list.has(kind) and not kind_review_table.has_row(
            kind
        )  # no engine row: asks nothing, as before
        assert (
            kind_review_table.row(kind)["review"] == "none"
            and kind_review_table.row(kind)["scored"] is False
        )
    assert (
        kind_review_table.row("datasheet")["scored"] is True
        and kind_list.family_of("datasheet") == "datasheet"
    )


def test_an_engine_row_for_a_kind_not_on_the_list_is_refused(monkeypatch):
    bad = json.loads((REF / "kind_review_table.json").read_text())
    bad["kinds"]["invented_kind"] = bad["kinds"]["unknown"]
    with pytest.raises(kind_review_table.TableError, match="not on the kind list"):
        kind_review_table._check(bad)


def test_a_kind_list_row_with_an_unknown_family_is_refused(tmp_path, monkeypatch):
    broken = json.loads((REF / "kind_list.json").read_text())
    broken["kinds"]["datasheet"]["family"] = "invented_family"
    path = tmp_path / "kind_list.json"
    path.write_text(json.dumps(broken))
    monkeypatch.setattr(kind_list, "PATH", path)
    with pytest.raises(kind_list.KindListError, match="family"):
        kind_list._data()


def test_the_unknown_and_other_kinds_have_no_family_and_no_guess():
    assert (
        kind_list.family_of(None) is None
        and kind_list.family_of("other") is None
        and kind_list.family_of("invented") is None
    )


def test_the_title_block_reader_and_the_standard_roles_name_only_kinds_on_the_list():
    assert set(document_kind.DOCUMENT_KINDS) == {
        *(k for k, r in kind_list.kinds().items() if r["cover_decided"]),
        "unknown",
    }
    roles = json.loads((REF / "standard_roles.json").read_text())["kinds_apply"]
    assert [k for k in roles if not kind_list.has(k)] == []


def test_the_old_to_new_mapping_every_kind_any_old_list_named_is_on_the_list_in_one_family():
    """The four old lists, merged: the sorter's 11, the engine's 8 (+ other, unknown), the paper-kind reading's 9 and the title-block
    reader's 9 are all on THE list, each in a family."""
    sorter = set(json.loads((REF / "document_kinds.json").read_text())["kinds"])
    engine = set(json.loads((REF / "kind_review_table.json").read_text())["kinds"]) - {
        "unknown",
        "other",
    }
    every = (
        sorter
        | engine
        | (set(paper_kind.PAPER_KINDS) - {"other"})
        | (set(document_kind.DOCUMENT_KINDS) - {"unknown"})
    )
    assert every == set(kind_list.kinds()) and all(
        kind_list.family_of(k) for k in every
    )
