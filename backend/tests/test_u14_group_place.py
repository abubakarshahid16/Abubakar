"""Update 14 (lead-4, 26 Nov 2026): the client's own groups must place real papers. Measured on a copy of live: 0 of 9 stored reviews
landed in one of the client's 93 groups, because a group's name was matched only word for word inside the subject and file name, and the
repository's invented example of the same kind was taken whenever no name matched. Now: a group also matches when every word of one of
its names stands in the paper's words in any order (plurals folded), or when it names the paper's equipment (the main word of the
equipment type the review recorded); and when the client's list is loaded, a paper is placed only in it, else in its family with no
group. Invented group names only."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import document_groups as DG
from app.config import settings


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    DG._load.cache_clear()
    yield tmp_path
    DG._load.cache_clear()


def _local(folder: Path, groups: dict) -> None:
    (folder / DG.LOCAL_NAME).write_text(
        json.dumps({"groups": groups}), encoding="utf-8"
    )
    DG._load.cache_clear()


INVENTED = {
    "g11": {
        "label": "Invented booster pumps data",
        "family": "datasheet",
        "kind": "datasheet",
        "words": ["invented booster pumps"],
    },
    "g12": {
        "label": "Invented holding tanks data",
        "family": "datasheet",
        "kind": "datasheet",
        "words": ["invented holding tanks"],
    },
    "g13": {
        "label": "Invented gizmo sizing note",
        "family": "study_calculation",
        "kind": "calculation",
        "words": ["gizmo sizing note"],
    },
    "g14": {
        "label": "Invented widget batteries list",
        "family": "list_register",
        "kind": None,
        "words": ["widget batteries list"],
    },
}


def test_a_datasheet_is_placed_by_the_equipment_its_review_recorded(data):
    _local(data, INVENTED)
    p = DG.place("datasheet", ["Datasheet of the feed unit, rev B"], "centrifugal_pump")
    assert (p.how, p.family, p.group) == (
        "kind",
        "datasheet",
        "g11",
    )  # "pumps" in the group's name, plural folded
    tank = DG.place("datasheet", ["Datasheet of the feed unit"], "storage_tank")
    assert tank.group == "g12"


def test_a_group_matches_when_every_word_of_its_name_stands_in_the_paper_in_any_order(
    data,
):
    _local(data, INVENTED)
    assert (
        DG.place("calculation", ["Note on the sizing of the gizmo skid"]).group == "g13"
    )
    assert (
        DG.place("other", ["the list of widget battery"]).group == "g14"
    )  # "batteries" and "battery"
    assert (
        DG.place("calculation", ["Note on the sizing of the pipe"]).group == "g13"
    )  # one calculation group: its kind places it


def test_with_the_clients_list_loaded_a_paper_is_never_placed_in_an_invented_example(
    data,
):
    repo = DG.place("datasheet", ["Datasheet of the unit"], "relief_valve")
    assert (
        repo.group == "datasheet"
    )  # no local file: the repository's example, as before
    _local(data, INVENTED)
    p = DG.place("datasheet", ["Datasheet of the unit"], "relief_valve")
    assert (p.how, p.family, p.group) == (
        "kind",
        "datasheet",
        None,
    )  # no group of the client's names a valve: family only
    assert DG.place("other", ["a datasheet"]).group not in {"datasheet", "contract"}


def test_a_kind_with_several_client_groups_and_no_named_one_keeps_its_family_only(data):
    _local(data, INVENTED)
    p = DG.place(
        "datasheet", ["Datasheet of the unit"]
    )  # two datasheet groups, neither named, no equipment: cannot choose
    assert (p.family, p.group) == ("datasheet", None)


def test_route_places_the_paper_by_the_equipment_the_review_recorded(data):
    _local(data, INVENTED)
    state = SimpleNamespace(identity=None, paper_id="doc_x", run_id="run_x")
    ident = {
        "kind": "datasheet",
        "subject": "Datasheet of the feed unit",
        "subject_key": "feed_unit",
        "equipment_type": "centrifugal_pump",
    }
    out = DG.route(None, state, ident, lambda i: dict(i))
    assert (
        state.identity["document_group"] == "g11"
        and state.identity["kind_placed"] == "kind"
    )
    assert (
        out == ident
    )  # a paper with a kind keeps its identity: placement is recorded, the review is unchanged


# ---- the owner's named equipment rule (26 Nov 2026, via lead-4): a group may LIST the equipment types it covers (taxonomy ids), e.g.
# relief-valve datasheets under an instrument datasheet group whose names never say "valve". Same match logic, strongest signal.

LISTED = {
    **INVENTED,
    "g15": {
        "label": "Invented instrument data sheets",
        "family": "datasheet",
        "kind": "datasheet",
        "words": ["invented instrument data sheets"],
        "equipment": ["relief_valve"],
    },
    "g16": {
        "label": "Invented valve sheets",
        "family": "datasheet",
        "kind": "datasheet",
        "words": ["invented valve sheets"],
    },
}


def test_a_group_that_lists_the_equipment_type_places_that_equipments_datasheets(data):
    _local(data, LISTED)
    p = DG.place("datasheet", ["Datasheet of the unit"], "relief_valve")
    assert (p.how, p.family, p.group) == (
        "kind",
        "datasheet",
        "g15",
    )  # listed beats a group that only names "valve"
    assert (
        DG.place("datasheet", ["Datasheet of the unit"], "gate_valve").group == "g16"
    )  # not listed: the word rule still works
    assert (
        DG.place("datasheet", ["Datasheet of the unit"], "centrifugal_pump").group
        == "g11"
    )


def test_a_listed_equipment_type_must_be_one_of_the_taxonomy(data):
    bad = {**LISTED, "g15": {**LISTED["g15"], "equipment": ["not_a_type"]}}
    _local(data, bad)
    with pytest.raises(DG.DocumentGroupsError, match="equipment"):
        DG.table()
