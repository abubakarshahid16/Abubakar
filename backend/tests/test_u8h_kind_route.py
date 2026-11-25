"""Builder H (planner 25 Nov 2026 23:35 (b) item 3): route by kind in code, one table, behind KIND_ROUTE_ENABLED (off). With the
switch off every kind routes exactly as before the table; the table starts equal to that; it can only narrow what runs."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app import kind_list, kind_route
from app.aim_review import library as L
from app.config import settings

#: Every kind the general review can hold: the method's kinds, G's whole kind list as the method spells it, and none.
ALL = sorted({*L.KINDS, *(L.method_kind(k) for k in kind_list.kinds())}) + [None, ""]


@pytest.fixture(autouse=True)
def _fresh_table():
    kind_route._load.cache_clear()
    yield
    kind_route._load.cache_clear()


@pytest.fixture
def switch(monkeypatch):
    def turn(on: bool):
        monkeypatch.setattr(settings, "kind_route_enabled", on)

    return turn


def test_the_switch_is_off_by_default():
    from app.config import Settings

    assert Settings.model_fields["kind_route_enabled"].default is False


@pytest.mark.parametrize("kind", ALL)
def test_switch_off_every_kind_routes_exactly_as_before_the_table(switch, kind):
    switch(False)
    r = kind_route.route(kind)
    assert r.source == "today"
    assert r.rules_of_kind == (L.KIND_LABELS.get(kind or "") or ("other",))
    assert r.method_books_kind == L.ROLE_KIND.get(kind or "")
    assert r.checklist_floor == kind_route.floor_today(kind) == L.floor_for(kind)
    assert r.skip_steps == frozenset() and r.reviewers == ("general",)
    assert all(r.runs(s) for s in kind_route.STEPS)


def test_the_table_starts_equal_to_today_for_every_kind():
    assert kind_route.differences_from_today(ALL) == []


def test_the_table_has_one_row_per_family_of_gs_kind_list():
    assert set(kind_route.table()["families"]) == set(kind_list.families())


@pytest.mark.parametrize(
    ("kind", "family", "reviewers"),
    [
        ("datasheet", "datasheet", ("general", "mechanical")),
        ("contract", "written_document", ("general", "contract")),
        ("procedure", "written_document", ("general",)),
        ("test record", "certificate_record", ("general", "mechanical")),
        ("other", None, ("general",)),
    ],
)
def test_switch_on_the_table_answers_by_family(switch, kind, family, reviewers):
    switch(True)
    r = kind_route.route(kind)
    assert (r.source, r.family, r.reviewers) == ("table", family, reviewers)


def _table(tmp_path, monkeypatch, edit) -> None:
    data = json.loads(kind_route.PATH.read_text(encoding="utf-8"))
    edit(data)
    p = tmp_path / "kind_route.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(kind_route, "PATH", p)
    kind_route._load.cache_clear()


def test_a_table_that_skips_a_step_no_one_may_skip_is_refused_and_the_review_routes_as_today(
    switch, tmp_path, monkeypatch
):
    switch(True)
    _table(
        tmp_path,
        monkeypatch,
        lambda d: d["families"]["datasheet"].update(skip_steps=["no_ask"]),
    )
    with pytest.raises(kind_route.RouteError):
        kind_route.table()
    assert kind_route.route("datasheet").source == "today"


def test_an_unreadable_table_routes_as_today(switch, tmp_path, monkeypatch):
    switch(True)
    monkeypatch.setattr(kind_route, "PATH", tmp_path / "missing.json")
    kind_route._load.cache_clear()
    assert kind_route.route("contract") == kind_route.today("contract")


def test_an_edited_table_changes_the_library_answers_only_with_the_switch_on(
    switch, tmp_path, monkeypatch
):
    _table(
        tmp_path,
        monkeypatch,
        lambda d: d["kinds"]["procedure"].update(checklist_floor=12),
    )
    switch(False)
    assert L.floor_for("procedure") == 30
    switch(True)
    assert L.floor_for("procedure") == 12
    assert L._route("procedure").method_books_kind == "procedure"


def _after_judge(monkeypatch, kind: str) -> list[str]:
    """Run the engine's after-judge steps with every step replaced by a recorder; returns the steps that ran."""
    from app import aim_review_gate
    from app.aim_review import (
        answered,
        asks,
        contract_code,
        editor,
        engine,
        references,
        second_read,
    )

    ran: list[str] = []
    monkeypatch.setattr(
        references,
        "check",
        lambda *a, **k: ran.append("reference_papers") or ([], set()),
    )
    monkeypatch.setattr(
        second_read, "s4c_second_read", lambda *a, **k: ran.append("second_read")
    )
    monkeypatch.setattr(
        answered, "s4b_answered", lambda *a, **k: ran.append("whole_paper_check")
    )
    monkeypatch.setattr(editor, "s5_edit", lambda *a, **k: ran.append("editor"))
    monkeypatch.setattr(asks, "mark", lambda *a, **k: ran.append("no_ask"))
    monkeypatch.setattr(
        contract_code, "add_lines", lambda *a, **k: ran.append("contract_code")
    )
    monkeypatch.setattr(aim_review_gate, "answered_check_on", lambda: True)
    state = SimpleNamespace(
        identity={"kind": kind},
        decided=[],
        answered=[],
        references=[],
        reference_ids=set(),
    )
    engine._after_judge(None, state, None, None, {}, frozenset(), "m", lambda *a: None)
    return ran


EVERY_STEP = [
    "reference_papers",
    "second_read",
    "whole_paper_check",
    "editor",
    "no_ask",
    "contract_code",
]


def test_switch_off_the_engine_runs_every_after_judge_step(switch, monkeypatch):
    switch(False)
    assert _after_judge(monkeypatch, "datasheet") == EVERY_STEP


def test_switch_on_the_starting_table_runs_every_step_too(switch, monkeypatch):
    switch(True)
    assert _after_judge(monkeypatch, "contract") == EVERY_STEP


def test_a_row_that_skips_a_step_narrows_only_its_own_family_and_never_the_no_ask_mark(
    switch, tmp_path, monkeypatch
):
    _table(
        tmp_path,
        monkeypatch,
        lambda d: d["families"]["datasheet"].update(
            skip_steps=["editor", "reference_papers"]
        ),
    )
    switch(True)
    assert _after_judge(monkeypatch, "datasheet") == [
        "second_read",
        "whole_paper_check",
        "no_ask",
        "contract_code",
    ]
    assert _after_judge(monkeypatch, "procedure") == EVERY_STEP
    switch(False)
    assert _after_judge(monkeypatch, "datasheet") == EVERY_STEP


#: Today's routing as printed from the code BEFORE the table existed (update 8, 25 Nov 2026): kind -> (rule labels, method-books
#: kind, checklist floor). Written out by hand, so a change to the constants or to the table is caught, not mirrored.
BEFORE = {
    "datasheet": (("datasheet",), "datasheet", 0),
    "procedure": (("procedure",), "procedure", 30),
    "contract": (("contract",), "contract", 30),
    "specification": (("contract",), "specification", 0),
    "drawing": (("drawing",), "drawing", 0),
    "calculation": (("calculation",), "datasheet", 0),
    "test record": (("other", "datasheet"), "datasheet", 0),
    "other": (("other",), None, 0),
}


@pytest.mark.parametrize("on", [False, True])
@pytest.mark.parametrize("kind", sorted(BEFORE))
def test_both_ways_every_method_kind_routes_as_the_code_did_before_the_table(
    switch, on, kind
):
    switch(on)
    r = kind_route.route(kind)
    assert (r.rules_of_kind, r.method_books_kind, r.checklist_floor) == BEFORE[kind]
    assert (
        L.floor_for(kind) == BEFORE[kind][2]
        and L._route(kind).method_books_kind == BEFORE[kind][1]
    )
