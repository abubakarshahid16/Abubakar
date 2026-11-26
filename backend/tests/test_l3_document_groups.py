"""L3 (planner 26 Nov 2026 14:45): the document groups are DATA (reference/document_groups.json), each in one family of the kind list;
a paper is routed by family; an unknown kind is never refused: nearest family, logged "new kind seen", labelled "not yet scored for
this kind". A paper whose kind is on the kind list (every scored kind) is placed by its kind and reviewed exactly as before.
Invented papers and words only; no paid call, no socket."""

from __future__ import annotations

import json
import logging

import pytest

from app import aim_review, aim_review_measured, kind_list
from app import document_groups as DG
from app.aim_review import engine as E
from app.aim_review import library as L
from app.config import settings
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    PAPER,
    MemoryStore,
    open_aim_db,
)


@pytest.fixture(autouse=True)
def _fresh():
    DG._load.cache_clear()
    yield
    DG._load.cache_clear()


def _table(tmp_path, monkeypatch, edit) -> None:
    data = json.loads(DG.PATH.read_text(encoding="utf-8"))
    edit(data)
    p = tmp_path / "document_groups.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(DG, "PATH", p)
    DG._load.cache_clear()


class _State:
    def __init__(self, run_id="run_l3", paper_id="doc_l3"):
        self.run_id, self.paper_id, self.identity = run_id, paper_id, {}


# ---- the data file ---------------------------------------------------------------------------------------------------------


def test_the_table_is_data_with_the_kind_lists_six_families_and_a_group_for_every_listed_kind():
    t = DG.table()
    assert set(t["families"]) == set(kind_list.families())
    assert {g["kind"] for g in t["groups"].values() if g["kind"]} == set(
        kind_list.kinds()
    )
    assert all(row["route_kind"] in L.KINDS for row in t["families"].values())


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d["families"].pop("datasheet"),
        lambda d: d["families"]["datasheet"].update(route_kind="nonsense"),
        lambda d: d["groups"]["drawing"].update(family="nonsense"),
        lambda d: d["groups"]["drawing"].update(kind="nonsense"),
        lambda d: d["groups"]["drawing"].update(words=["Upper Case"]),
        lambda d: d.update(default_family="nonsense"),
    ],
)
def test_a_malformed_table_is_refused_by_its_reader(tmp_path, monkeypatch, edit):
    _table(tmp_path, monkeypatch, edit)
    with pytest.raises(DG.DocumentGroupsError):
        DG.table()


def test_the_routing_switch_is_off_by_default():
    from app.config import Settings

    # update 12 review B1: on by default it changed a Claude review of an `other` paper (the owner's baseline forbids it)
    assert Settings.model_fields["kind_family_route_enabled"].default is False


# ---- a listed kind: placed by its kind, routed as before (every scored kind) --------------------------------------------------


@pytest.mark.parametrize("kind", [*L.KINDS[:-1], *kind_list.kinds()])
def test_a_kind_on_the_list_keeps_its_kind_and_family(kind):
    p = DG.place(
        kind, ["invented widget logbook", "piping isometric"]
    )  # words of other groups never move a listed kind
    assert (p.how, p.family, p.route_kind, p.new_kind_seen) == (
        "kind",
        kind_list.family_of(kind),
        None,
        False,
    )


@pytest.mark.parametrize(
    "kind", ["datasheet", "contract", "procedure", "specification"]
)
def test_route_leaves_a_scored_kinds_identity_exactly_as_before(kind):
    ident = {
        "kind": kind,
        "equipment_type": "pump",
        "subject": "invented subject",
        "subject_key": "invented_key",
        "cited": [],
    }
    state = _State()
    got = DG.route(None, state, dict(ident), E._identity_record)
    assert got == ident  # the later steps get the very same identity
    before = E._identity_record(ident)
    assert {k: state.identity[k] for k in before} == before
    assert (
        state.identity["kind_placed"] == "kind"
        and "reviewed_as" not in state.identity
        and not state.identity["new_kind_seen"]
    )


def test_a_scored_kinds_score_line_is_unchanged_by_the_placement():
    ident = {"kind": "datasheet", "equipment_type": "pump"}
    placed = {
        **ident,
        "family": "datasheet",
        "document_group": "datasheet",
        "kind_placed": "kind",
        "new_kind_seen": False,
    }
    assert aim_review_measured.for_run(placed) == aim_review_measured.for_run(ident)


# ---- an unknown kind: never refused -------------------------------------------------------------------------------------------


def test_an_unlisted_kind_named_by_a_groups_words_takes_that_groups_family():
    p = DG.place("other", ["a piping isometric for line one", ""])
    assert (p.how, p.group, p.family, p.route_kind, p.new_kind_seen) == (
        "group",
        "drawing",
        "drawing_diagram",
        "drawing",
        False,
    )


def test_a_kind_no_list_holds_goes_to_the_nearest_family_by_shared_words(
    tmp_path, monkeypatch
):
    _table(
        tmp_path,
        monkeypatch,
        lambda d: d["groups"].update(
            zz_register={
                "label": "Invented register",
                "family": "list_register",
                "kind": None,
                "words": ["invented register of widgets"],
            }
        ),
    )
    p = DG.place(
        "other", ["a widgets log"]
    )  # shares "widgets" with the list family, names no group whole
    assert (p.how, p.family, p.group, p.new_kind_seen) == (
        "nearest",
        "list_register",
        None,
        True,
    )


def test_a_kind_sharing_no_word_goes_to_the_default_family_and_is_new():
    p = DG.place(None, ["zzqx vrrk"])
    assert (p.how, p.family, p.new_kind_seen) == (
        "default",
        DG.table()["default_family"],
        True,
    )


def test_a_new_kind_is_logged_and_recorded_and_its_steps_use_the_familys_route_kind(
    caplog, monkeypatch, tmp_path
):
    _table(
        tmp_path,
        monkeypatch,
        lambda d: d["families"]["written_document"].update(route_kind="procedure"),
    )
    monkeypatch.setattr(settings, "kind_family_route_enabled", True)
    state = _State(run_id="run_new_kind")
    with caplog.at_level(logging.INFO, logger="app.document_groups"):
        got = DG.route(
            None,
            state,
            {"kind": "other", "subject": "zzqx vrrk", "subject_key": "zzqx"},
            E._identity_record,
        )
    assert (
        "run_new_kind: new kind seen" in caplog.text and "zzqx" not in caplog.text
    )  # ids and codes only, no paper words
    assert got["kind"] == "procedure"
    assert (
        state.identity["kind"],
        state.identity["reviewed_as"],
        state.identity["new_kind_seen"],
    ) == ("other", "procedure", True)


def test_the_way_back_switch_off_reviews_an_other_paper_as_other_but_still_places_and_labels_it(
    monkeypatch,
):
    monkeypatch.setattr(settings, "kind_family_route_enabled", False)
    state = _State()
    got = DG.route(
        None,
        state,
        {"kind": "other", "subject": "piping isometric"},
        E._identity_record,
    )
    assert got["kind"] == "other" and "reviewed_as" not in state.identity
    assert (
        state.identity["kind_placed"] == "group"
        and DG.not_scored(state.identity) is not None
    )


def test_a_table_that_cannot_be_read_routes_nothing_and_the_run_says_the_step_did_not_run(
    tmp_path, monkeypatch
):
    from app.aim_review import faults

    monkeypatch.setattr(DG, "PATH", tmp_path / "missing.json")
    calls: list = []
    state = _State()
    with faults.recording(calls):
        got = DG.route(
            None,
            state,
            {"kind": "other", "subject": "piping isometric"},
            E._identity_record,
        )
    assert (
        got == {"kind": "other", "subject": "piping isometric"}
        and "kind_placed" not in state.identity
    )
    assert [c.step for c in calls] == ["aim_document_group"] and calls[0].ok is False


# ---- the label on the page and the comment sheet --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("placed", "says"),
    [
        (
            {
                "kind_placed": "group",
                "family": "drawing_diagram",
                "document_group": "drawing",
            },
            "Drawing, a kind of document",
        ),
        (
            {"kind_placed": "nearest", "family": "list_register"},
            "has not seen before (new kind seen)",
        ),
        (
            {"kind_placed": "default", "family": "written_document"},
            "the general family",
        ),
    ],
)
def test_a_paper_not_placed_by_its_kind_is_labelled_not_yet_scored_for_this_kind(
    placed, says
):
    got = aim_review_measured.for_run({"kind": "other", **placed})
    assert (
        got["sentence"].startswith("Not yet scored for this kind: ")
        and says in got["sentence"]
    )
    assert got["found"] is None and got["verdict"] == DG.NOT_SCORED
    local = aim_review_measured.for_local_run(
        {"kind": "other", **placed}, ["invented-local-model"]
    )
    assert "Not yet scored for this kind" in local["sentence"]


def test_an_older_run_with_no_placement_keeps_its_old_score_line():
    assert DG.not_scored({"kind": "other"}) is None
    assert (
        aim_review_measured.for_run({"kind": "other"})["sentence"]
        == "This kind has not been measured on test copies yet."
    )


# ---- the proof: made-up papers of kinds on no list, through a whole review ---------------------------------------------------------


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


def _run(conn, subject_key):
    model = E.FakeModel(kind="other", subject_key=subject_key)
    r = aim_review.run(conn, run_id="run_l3_" + subject_key, paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}),
                       store=MemoryStore(), max_usd=5.0, model=model)  # fmt: skip
    return r


def test_a_made_up_paper_of_a_kind_on_no_list_is_reviewed_never_refused_and_labelled(
    aim_db, monkeypatch
):
    monkeypatch.setattr(settings, "kind_family_route_enabled", True)
    r = _run(aim_db, "zzqx_vrrk_logbook")
    assert r.status == "done", r.stop_reason
    assert r.lines  # reviewed: the always-on items at least
    i = r.identity
    assert (i["kind"], i["new_kind_seen"], i["kind_placed"]) == (
        "other",
        True,
        "default",
    )
    from app import aim_review_local_view

    assert aim_review_local_view.measured(i, {"local": False})["sentence"].startswith(
        "Not yet scored for this kind: "
    )


def test_a_made_up_paper_named_by_a_groups_words_is_reviewed_with_that_familys_kind(
    aim_db, monkeypatch
):
    monkeypatch.setattr(settings, "kind_family_route_enabled", True)
    r = _run(aim_db, "piping_isometric_sheet")
    assert r.status == "done", r.stop_reason
    assert (r.identity["family"], r.identity["reviewed_as"]) == (
        "drawing_diagram",
        "drawing",
    )
    assert r.checklist_key.startswith(
        "drawing"
    )  # the checklist is the drawing family's
    monkeypatch.setattr(settings, "kind_family_route_enabled", False)
    off = aim_review.run(aim_db, run_id="run_l3_off", paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}), store=MemoryStore(),
                         max_usd=5.0, model=E.FakeModel(kind="other", subject_key="piping_isometric_sheet"))  # fmt: skip
    assert off.checklist_key.startswith("other") and "reviewed_as" not in off.identity
