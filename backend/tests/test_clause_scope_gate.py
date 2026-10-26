"""Order 161 B (extends #141): the division gate by part, in the gate itself.

What the gate decides for a part whose own scope limits it to a construction:
unsure goes to the engineer; a "yes" counts only when a stated line backs it;
every requirement compared without its part being read is COUNTED, with its
boundary; the scope clause is read wherever the part opens; sub-parts and
candidate starts that `clause_scope` proposes run through the same decision.

`clause_scope` is replaced by a stub (`StubScope`), so these tests do not
depend on how it finds headings. Invented standard text and datasheet values
only (rule 13): no real standard, part, material grade or layout.
"""

from __future__ import annotations

import logging
import sys

import pytest

import app as app_package
from app import ai_applicability, clause_scope, scope_ledger, subject_scope
from app.config import settings
from app.reasoning_provider import ProviderRefused
from tests.test_141_division_scope import (  # noqa: F401 - temp_storage is a fixture
    GENERAL,
    GRAPHITE,
    LIMITED,
    LIMITED_TT,
    NOT_GRAPHITE,
    NOT_LIMITED,
    PAGES,
    SPECIAL,
    STEEL,
    TITAN,
    ZZ_SCOPE,
    FakeModel,
    _gate,
    _ids,
    _review,
    temp_storage,
)

TI_SCOPE = "The rules in this part are applicable to vessels constructed of titanium."
LIMITED_TI = {
    "limited": "yes",
    "construction": "constructed of titanium",
    "quote": TI_SCOPE,
}
UNSURE = {"limited": "unsure", "construction": None, "quote": None}

# order 210: a held requirement is an engineer row, never a verdict
HELD_ROW = {"NEEDS_ENGINEER_REVIEW"}


def req(rid: str, page: int, sentence: str) -> dict:
    return {
        "id": rid,
        "standard_document_id": "std",
        "page": page,
        "requirement_text": sentence,
        "source_text": sentence,
    }


def titanium_if_named(passage: str) -> dict:
    """A reader that finds the limit wherever the passage holds the sentence."""
    return LIMITED_TI if TI_SCOPE in passage else NOT_LIMITED


class StubScope:
    """Stands in for `app.clause_scope` (same four functions, fixed answers)."""

    MAX_TITLES = 60

    def __init__(self) -> None:
        self.heads: list[str] = []  # lines offered as candidate starts
        self.subs: list[tuple[str, str | None]] = []  # (title, title that ends it)
        self.flag = True
        self.seen: dict = {}

    def candidate_starts(self, text, divs):
        return [
            {"at": text.offsets[i], "line": i, "heading": line, "kind": "shape"}
            for i, line in enumerate(text.lines)
            if line in self.heads
        ]

    def subclause_units(self, text, div, end, wanted_lines, limit=None):
        self.seen["wanted"] = set(wanted_lines)
        out = []
        for title, until in self.subs:
            first = text.lines.index(title)
            last = text.lines.index(until) if until else len(text.lines)
            out.append(
                {
                    "line": first,
                    "at": text.offsets[first],
                    "end": text.offsets[last],
                    "title": title,
                }
            )
        return out

    def screen_titles(self, units, provider, run):
        self.seen["screened"] = [u["title"] for u in units]
        return list(units) if self.flag else []

    def downgrade(self, verdict):
        return "held" if verdict in ("does_not_apply", "held") else "kept"


@pytest.fixture
def stub(monkeypatch, temp_storage):  # noqa: F811 - the fixture of test_141
    fake = StubScope()
    monkeypatch.setitem(sys.modules, "app.clause_scope", fake)
    monkeypatch.setattr(app_package, "clause_scope", fake, raising=False)
    return fake


def gate(model, pages, reqs, *, facts=STEEL, limit=None):
    return ai_applicability.division_gate(
        [dict(r) for r in reqs],
        classification={"equipment_type": "Pressure vessel"},
        facts=facts,
        standard_labels={"std": "XYZ code"},
        provider=model,
        pages_of=lambda sid: pages,
        limit=limit,
    )


# --------------------------------------------------------------- D1.1: unsure


def test_an_unsure_part_is_held_for_the_engineer_and_a_no_is_kept(stub):
    model = FakeModel(scope=lambda p: UNSURE if "Part ZZ" in p else NOT_LIMITED)
    out = _gate(model, reqs=(GENERAL, SPECIAL))
    assert _ids(out["kept"]) == ["aa"] and _ids(out["held"]) == ["zz"]
    [held] = out["held"]
    assert held["code"] == "applicability_unsure"
    assert (
        "could not tell" in held["detail"] and "an engineer decides" in held["detail"]
    )
    assert held["decided_by"] == "ai:test-model+code"
    assert out["summary"]["requirements_held_unsure"] == 1
    assert out["summary"]["requirements_gated"] == 2


def test_a_part_the_model_calls_not_limited_is_kept(stub):
    out = _gate(FakeModel(scope=NOT_LIMITED), reqs=(GENERAL, SPECIAL))
    assert _ids(out["kept"]) == ["aa", "zz"] and out["held"] == []
    assert "requirements_held_unsure" not in out["summary"]


# ------------------------------------------------------ D1.2: a yes is checked


@pytest.mark.parametrize(
    "reply",
    [
        # the quoted line is stated, but it does not name the part's construction
        {**NOT_GRAPHITE, "is_that": "yes"},
        # the quote is not one of the stated lines at all
        {
            "equipment_is": "Impervious graphite block",
            "quote": "Shell material: Impervious graphite block",
            "is_that": "yes",
        },
    ],
)
def test_a_yes_that_no_stated_line_backs_is_held_not_kept(stub, reply):
    out = _gate(FakeModel(construction=reply), reqs=(SPECIAL,))
    assert _ids(out["held"]) == ["zz"] and out["kept"] == []


def test_a_yes_backed_by_the_stated_line_that_names_it_is_kept(stub):
    yes = {
        "equipment_is": "Impervious graphite block",
        "quote": "Shell material: Impervious graphite block",
        "is_that": "yes",
    }
    out = _gate(FakeModel(construction=yes), facts=GRAPHITE, reqs=(SPECIAL,))
    assert _ids(out["kept"]) == ["zz"] and out["held"] == [] and out["items"] == []


# ------------------------------------------------- D1.3: the counts, boundaries


def test_requirements_beyond_the_limit_are_held_and_counted(stub):
    model = FakeModel()
    out = gate(model, PAGES, (GENERAL, SPECIAL, TITAN), limit=1)
    # the part read is Part AA; the others were never read, so nothing is
    # compared on them: held for the engineer, not kept
    assert _ids(out["kept"]) == ["aa"] and out["items"] == []
    assert _ids(out["held"]) == ["zz", "tt"]
    for held in out["held"]:
        assert held["code"] == "applicability_unsure"
        assert held["decided_by"] == "code:scope-not-read"
        assert "limit on parts read was reached" in held["detail"]
        assert "an engineer decides" in held["detail"]
    summary = out["summary"]
    assert summary["requirements_beyond_limit"] == 2
    assert summary["requirements_gated"] == 3 and summary["not_read_limit"] == 2
    assert model.calls == ["division"]  # one read: the limit is the run's, not a part's
    # a count of none is left out, never shown as 0
    for absent in (
        "requirements_held_scope_not_read",
        "requirements_unplaced",
        "model_unavailable",
        "requirements_subparts_not_screened",
    ):
        assert absent not in summary  # a count of none is left out, never 0


def test_requirements_of_parts_nobody_could_read_are_held_and_counted(stub):
    out = gate(
        FakeModel(fail="the model could not be reached"),
        PAGES,
        (GENERAL, SPECIAL, TITAN),
    )
    assert out["kept"] == [] and out["items"] == []
    assert _ids(out["held"]) == ["aa", "zz", "tt"]
    assert {h["decided_by"] for h in out["held"]} == {"code:scope-not-read"}
    summary = out["summary"]
    assert summary["requirements_held_scope_not_read"] == 3
    assert summary["requirements_gated"] == 3 and summary["held"] == 3
    assert "requirements_beyond_limit" not in summary
    assert "requirements_in_unread_divisions" not in summary  # the old kept count


def test_a_model_that_is_down_for_the_whole_run_is_said_once(stub):
    reason = "the model could not be reached"
    out = gate(FakeModel(fail=reason), PAGES, (GENERAL, SPECIAL, TITAN))
    assert reason in out["summary"]["model_unavailable"]
    assert "stopped" in out["summary"]  # kept: how the run ended
    # nothing the model never read is a pass, and nothing is capped
    assert len(out["held"]) == 3 and out["kept"] == []
    up = gate(FakeModel(), PAGES, (GENERAL, SPECIAL, TITAN))
    assert "model_unavailable" not in up["summary"]


def test_a_reply_that_cannot_be_used_holds_the_part_and_nothing_else(stub):
    made_up = {**LIMITED_TT, "quote": "Titanium is wonderful and also very light."}
    model = FakeModel(scope=lambda p: made_up if "Part TT" in p else NOT_LIMITED)
    out = gate(model, PAGES, (GENERAL, SPECIAL, TITAN))
    assert _ids(out["kept"]) == ["aa", "zz"] and _ids(out["held"]) == ["tt"]
    [held] = out["held"]
    assert held["decided_by"] == "code:scope-not-read"
    assert "did not read this part's scope sentence" in held["detail"]
    assert "unavailable, timed out, or an invalid reply" in held["detail"]
    assert "PART TT" in held["detail"] and "XYZ code" in held["detail"]
    summary = out["summary"]
    assert summary["requirements_held_scope_not_read"] == 1
    assert "model_unavailable" not in summary  # the model was up


def test_the_construction_step_failing_holds_the_part_and_is_counted_apart(stub):
    model = FakeModel(construction={"nonsense": 1})  # fits no schema
    out = gate(model, PAGES, (GENERAL, SPECIAL, TITAN))
    assert _ids(out["kept"]) == ["aa"] and _ids(out["held"]) == ["zz", "tt"]
    assert out["summary"]["requirements_held_construction_not_read"] == 2
    assert "requirements_held_scope_not_read" not in out["summary"]
    assert ZZ_SCOPE in out["held"][0]["detail"]  # the standard's own sentence only


def test_with_the_reader_switched_off_nothing_is_held_or_read(monkeypatch):
    monkeypatch.setattr(settings, "ai_division_scope_enabled", False)
    reqs = [dict(GENERAL), dict(SPECIAL)]
    out = ai_applicability.division_gate_for_run(reqs, {}, [], {})
    assert out["kept"] == reqs and out["held"] == [] and out["items"] == []
    assert out["summary"] is None


def test_a_requirement_that_cannot_be_placed_is_kept_and_counted(stub):
    lost = req("lost", 99, "x")
    out = gate(FakeModel(), PAGES, (GENERAL, lost))
    assert _ids(out["kept"]) == ["aa", "lost"]
    assert out["summary"]["requirements_unplaced"] == 1
    assert out["summary"]["requirements_gated"] == 2


# --------------------------------------------- D2.1: the limit under a preamble


def test_the_scope_sentence_under_a_general_heading_with_a_preamble_is_read():
    sentence = "This Appendix applies to windows made of acrylic plastic."
    text = subject_scope.StandardText(
        [
            (
                1,
                "PART AA\nRULES FOR VIEWPORTS\nAA-1 GENERAL\n"
                "First line of background.\nSecond line of background.\n"
                "Third line of background.\nFourth line of background.\n"
                + sentence
                + "\nAA-2 The window design life shall be at least 10 years.\n",
            )
        ]
    )
    [div] = ai_applicability.divisions(text)
    assert subject_scope._heading("AA-1 GENERAL") is not None
    passage = ai_applicability.scope_passage(text, div, None)
    assert ai_applicability.folded_in(sentence, passage)
    # the next sub-clause is not read as the part's own
    assert "design life" not in passage


# ------------------------------------------------------- D2.2: sub-part wiring

SUB_PAGE = (
    1,
    "PART AA\nGENERAL REQUIREMENTS FOR ALL VESSELS\nAA-1 SCOPE\n"
    "The rules of Part AA apply to all vessels of this code.\n"
    "AA-2 The shell thickness shall be at least 6 mm.\nAA-9 LININGS\n"
    + TI_SCOPE
    + "\nAA-10 Lining joints shall be polished flush.\nAA-11 NAMEPLATES\n"
    "AA-12 The nameplate shall be of stainless steel.\n",
)
SHELL = req("shell", 1, "AA-2 The shell thickness shall be at least 6 mm.")
JOINT = req("joint", 1, "AA-10 Lining joints shall be polished flush.")
PLATE = req("plate", 1, "AA-12 The nameplate shall be of stainless steel.")


def test_a_flagged_sub_part_is_read_and_excludes_only_its_own_requirements(stub):
    stub.subs = [("AA-9 LININGS", "AA-11 NAMEPLATES")]
    out = gate(FakeModel(scope=titanium_if_named), [SUB_PAGE], (SHELL, JOINT, PLATE))
    assert _ids(out["items"]) == ["joint"] and _ids(out["kept"]) == ["shell", "plate"]
    [item] = out["items"]
    assert item["code"] == "outside_division_scope"
    assert "AA-9 LININGS" in item["detail"] and TI_SCOPE in item["detail"]
    # the model is shown only the titles of sub-headings that hold a requirement
    assert stub.seen["screened"] == ["AA-9 LININGS"] and stub.seen["wanted"]
    assert out["summary"]["subparts_flagged"] == 1


def test_a_sub_part_the_model_did_not_flag_changes_nothing(stub):
    stub.subs = [("AA-9 LININGS", "AA-11 NAMEPLATES")]
    stub.flag = False
    out = gate(FakeModel(scope=titanium_if_named), [SUB_PAGE], (SHELL, JOINT, PLATE))
    assert _ids(out["kept"]) == ["shell", "joint", "plate"] and out["items"] == []
    assert "subparts_flagged" not in out["summary"]


# ------------------------------------- D3: candidate starts and breaks, wiring

AA_PAGE = PAGES[0]


def assert_a_hold_for_the_engineer(detail: str) -> None:
    """The hold quotes the standard's scope sentence and the datasheet's stated
    line, and says an engineer decides."""
    assert TI_SCOPE in detail and '"Shell material: Carbon steel plate XQ-70' in detail
    assert "found by its shape" in detail and "an engineer decides" in detail


@pytest.mark.parametrize(
    "heading",
    [
        "SECTION 8 RULES FOR TITANIUM",
        "DIVISION 8 RULES FOR TITANIUM",
        "APPENDIX 8.1 RULES FOR TITANIUM",
        "APPENDIX 12-A RULES FOR TITANIUM",
        "Appendix 3-2 Rules for titanium",
        "Appendix 8. Rules for titanium",
        "Supplement 8 Rules for titanium",
        "Annex A-1 Rules for titanium",
    ],
)
def test_a_part_with_a_heading_of_another_shape_is_read_and_held(stub, heading):
    page = (2, f"{heading}\n{TI_SCOPE}\nXX-2 Titanium welds shall be shielded.\n")
    weld = req("weld", 2, "XX-2 Titanium welds shall be shielded.")
    named = [
        d["name"]
        for d in ai_applicability.divisions(subject_scope.StandardText([AA_PAGE, page]))
        if d["name"]
    ]
    assert named == [("part", "AA")]  # the finder alone does not see it
    stub.heads = [heading]
    out = gate(FakeModel(scope=titanium_if_named), [AA_PAGE, page], (GENERAL, weld))
    # found by shape, so it can only HOLD (never excluded), with the reasons
    assert _ids(out["held"]) == ["weld"] and _ids(out["kept"]) == ["aa"]
    assert out["items"] == [] and out["summary"]["candidates_read"] == 1
    assert_a_hold_for_the_engineer(out["held"][0]["detail"])


def test_a_heading_in_the_middle_of_a_page_is_read_and_held_not_skipped(stub):
    filler = "".join(f"Background line {n} of the code.\n" for n in range(8))
    page = (
        2,
        filler
        + "PART TT\nREQUIREMENTS FOR TITANIUM VESSELS\nTT-1 SCOPE\n"
        + TI_SCOPE
        + "\nTT-2 Titanium welds shall be shielded on both sides.\n",
    )
    out = gate(
        FakeModel(scope=titanium_if_named),
        [AA_PAGE, page],
        (GENERAL, TITAN | {"page": 2}),
    )
    assert _ids(out["held"]) == ["tt"] and _ids(out["kept"]) == ["aa"]
    assert out["items"] == []
    assert_a_hold_for_the_engineer(out["held"][0]["detail"])


JACKET_PAGE = (
    4,
    "".join(f"Background line {n} of the code.\n" for n in range(6))
    + "Appendix 9 (jacketed vessels)\nwhere a jacket is used.\n"
    "J-1 Jackets shall be pressure tested.\n",
)
JACKET = req("jacket", 4, "J-1 Jackets shall be pressure tested.")


def test_a_start_the_model_does_not_confirm_inherits_the_part_before_as_a_hold(stub):
    # Part TT (excluded) is read for its follower only: it has no requirement
    # of its own in this run
    out = gate(FakeModel(), [*PAGES, JACKET_PAGE], (JACKET,))
    assert _ids(out["held"]) == ["jacket"] and out["items"] == [] and out["kept"] == []
    [held] = out["held"]
    assert held["code"] == "applicability_unsure"
    assert "Appendix 9 (jacketed vessels)" in held["detail"]
    assert "an engineer decides" in held["detail"]


def test_a_start_that_could_not_be_read_is_held_not_kept(stub):
    stub.heads = ["Appendix 9 (jacketed vessels)"]
    unusable = {**LIMITED_TI, "quote": "A sentence that the standard does not hold."}
    model = FakeModel(scope=lambda p: unusable if "Appendix 9" in p else NOT_LIMITED)
    out = gate(model, [AA_PAGE, (2, JACKET_PAGE[1])], (GENERAL, JACKET | {"page": 2}))
    assert _ids(out["kept"]) == ["aa"] and _ids(out["held"]) == ["jacket"]
    assert out["held"][0]["decided_by"] == "code:scope-not-read"
    assert out["summary"]["requirements_held_scope_not_read"] == 1


def test_a_flagged_sub_part_that_could_not_be_read_holds_only_its_requirements(stub):
    stub.subs = [("AA-9 LININGS", "AA-11 NAMEPLATES")]
    unusable = {**LIMITED_TI, "quote": "A sentence that the standard does not hold."}
    model = FakeModel(scope=lambda p: unusable if "LININGS" in p else NOT_LIMITED)
    out = gate(model, [SUB_PAGE], (SHELL, JOINT, PLATE))
    assert _ids(out["kept"]) == ["shell", "plate"] and _ids(out["held"]) == ["joint"]
    [held] = out["held"]
    assert held["decided_by"] == "code:scope-not-read"
    assert "AA-9 LININGS" in held["detail"]  # the sub-heading, nothing more of the text
    assert out["summary"]["requirements_held_scope_not_read"] == 1


def test_a_start_the_model_does_not_confirm_after_a_kept_part_is_kept(stub):
    out = gate(
        FakeModel(scope=NOT_LIMITED),
        [AA_PAGE, (2, JACKET_PAGE[1])],
        (JACKET | {"page": 2},),
    )
    assert _ids(out["kept"]) == ["jacket"] and out["held"] == [] and out["items"] == []


def test_a_cross_reference_inside_an_excluded_part_does_not_rescue_what_follows(stub):
    wrapped = (
        4,
        "TT-9 Tubes\nshall be\nmarked and\nthen tested\nas in the rules of\n"
        "Part AA\nand marked.\nTT-10 Titanium joints shall be marked.\n",
    )
    joint = req("tj", 4, "TT-10 Titanium joints shall be marked.")
    out = gate(FakeModel(), [*PAGES, wrapped], (joint,))
    assert _ids(out["held"]) == ["tj"] and out["kept"] == [] and out["items"] == []


# ------------------------------------------------ privacy and honesty of text


def test_the_detail_quotes_only_the_standard_and_the_stated_line_and_logs_nothing(
    stub, caplog
):
    with caplog.at_level(logging.DEBUG):
        out = _gate(FakeModel(), reqs=(GENERAL, SPECIAL, TITAN))
    [item] = out["items"]
    assert item["decided_by"] == "ai:test-model+code"
    assert '"Shell material: Carbon steel plate XQ-70' in item["detail"]
    assert "XYZ code" in item["detail"] and "Part TT" in item["detail"]
    [held] = out["held"]
    assert ZZ_SCOPE in held["detail"] and held["decided_by"] == "ai:test-model+code"
    # nothing of the standard or the datasheet reaches a log
    for secret in (ZZ_SCOPE, "Carbon steel plate", "shell thickness", "PART TT"):
        assert secret not in caplog.text


# --------------------------------------------------------------- on a review


def test_a_review_holds_an_unsure_part_and_stores_the_counts(stub, monkeypatch):
    model = FakeModel(scope=lambda p: UNSURE if "Part ZZ" in p else NOT_LIMITED)
    result, stored, ids = _review(monkeypatch, model)
    assert stored[ids["zz"]]["state"] == scope_ledger.APPLIES_NOT_CHECKED
    assert stored[ids["zz"]]["reason_code"] == "applicability_unsure"
    assert stored[ids["aa"]]["state"] == scope_ledger.CHECKED
    assert {f["compliance_status"] for f in result["findings"]
                if f.get("requirement_id") == ids["zz"]} <= HELD_ROW
    counts = result["requirement_split"]["division_scope"]
    assert counts["requirements_held_unsure"] == 1
    assert counts["requirements_gated"] == 3


def test_a_review_with_the_reader_off_stores_no_counts(stub, monkeypatch):
    model = FakeModel(scope=UNSURE)
    result, stored, ids = _review(monkeypatch, model, enabled=False)
    assert {stored[i]["state"] for i in ids.values()} == {scope_ledger.CHECKED}
    assert model.calls == [] and "division_scope" not in result["requirement_split"]
    assert settings.ai_division_scope_enabled is False


# ------------------------- nested sub-parts, unsure candidates, what was not screened


@pytest.fixture
def store(temp_storage):  # noqa: F811 - the fixture of test_141; the REAL clause_scope
    yield


NEST_PAGE = (
    1,
    "PART AA\nGENERAL REQUIREMENTS FOR ALL VESSELS\n1.1 SCOPE\n"
    "The rules of Part AA apply to all vessels of this code.\n"
    "4.1 Welded items\n" + TI_SCOPE + "\n"
    "4.1.1 Seals\nSeals shall be replaced every two years.\n"
    "4.1.2 Gaskets\nGaskets are listed in the schedule.\n"
    "4.2 Nameplates\nThe nameplate shall be of stainless steel.\n",
)
SEAL = req("seal", 1, "Seals shall be replaced every two years.")
SEAL_OUT = req("plate", 1, "The nameplate shall be of stainless steel.")
NESTED = [("4.1.1 Seals", "4.1.2 Gaskets"), ("4.1 Welded items", "4.2 Nameplates")]


def flags(*titles):
    """A model that flags the given sub-heading titles and reads a limit
    wherever its passage holds the titanium sentence."""
    model = FakeModel(scope=titanium_if_named)
    model.replies["titles"] = lambda prompt: {"titles": list(titles)}
    return model


def test_a_requirement_in_a_nested_flagged_sub_part_meets_the_outer_limit_too(
    store,
):
    # the REAL clause_scope: the outer sub-part holds no requirement directly
    model = flags("4.1 Welded items", "4.1.1 Seals")
    out = gate(model, [NEST_PAGE], (SEAL, SEAL_OUT))
    assert _ids(out["items"]) == ["seal"] and _ids(out["kept"]) == ["plate"]
    [item] = out["items"]
    assert "4.1 Welded items" in item["detail"] and TI_SCOPE in item["detail"]
    assert out["summary"]["subparts_flagged"] == 2


def test_a_nested_requirement_takes_the_most_restrictive_of_its_sub_parts(stub):
    stub.subs = NESTED
    model = FakeModel(scope=lambda p: UNSURE if TI_SCOPE in p else NOT_LIMITED)
    out = gate(model, [NEST_PAGE], (SEAL,))
    assert _ids(out["held"]) == ["seal"] and out["kept"] == []


def test_an_outer_exclusion_beats_an_inner_part_that_is_not_limited(stub):
    # the inner part says "no limit", the outer one excludes: excluded wins
    stub.subs = NESTED
    out = gate(FakeModel(scope=titanium_if_named), [NEST_PAGE], (SEAL,))
    assert _ids(out["items"]) == ["seal"] and out["held"] == []


def test_a_flagged_outer_sub_part_that_was_not_read_is_counted(stub):
    stub.subs = NESTED
    # reads: the part, the title screen, the inner sub-part; none is left
    out = gate(FakeModel(scope=titanium_if_named), [NEST_PAGE], (SEAL,), limit=3)
    assert out["kept"] == [] and out["items"] == []
    assert _ids(out["held"]) == ["seal"]
    assert out["held"][0]["decided_by"] == "code:scope-not-read"
    assert out["summary"]["requirements_beyond_limit"] == 1


def test_a_start_the_model_is_unsure_of_holds_even_after_a_kept_part(stub):
    stub.heads = ["Appendix 9 (jacketed vessels)"]
    model = FakeModel(scope=lambda p: UNSURE if "Appendix 9" in p else NOT_LIMITED)
    out = gate(model, [AA_PAGE, (2, JACKET_PAGE[1])], (JACKET | {"page": 2},))
    assert _ids(out["held"]) == ["jacket"] and out["kept"] == []
    assert "could not tell" in out["held"][0]["detail"]
    assert out["summary"]["requirements_held_unsure"] == 1


def test_sub_headings_not_screened_because_the_limit_is_spent_are_held(stub):
    stub.subs = [("4.1 Welded items", "4.2 Nameplates")]
    model = FakeModel(scope=titanium_if_named)
    out = gate(model, [NEST_PAGE], (SEAL, SEAL_OUT), limit=1)
    assert out["kept"] == [] and "screened" not in stub.seen
    assert _ids(out["held"]) == ["seal", "plate"]
    assert "did not screen the sub-headings" in out["held"][0]["detail"]
    assert out["held"][0]["decided_by"] == "code:scope-not-read"
    assert out["summary"]["requirements_subparts_not_screened"] == 2
    assert out["summary"]["requirements_gated"] == 2


def test_sub_headings_not_screened_because_the_model_stopped_are_held(store):
    class Down(FakeModel):
        def reason(self, packet):
            if packet.prompt.startswith("The TEXT is a list of sub-heading titles"):
                raise ProviderRefused("the model could not be reached")
            return super().reason(packet)

    out = gate(Down(scope=NOT_LIMITED), [NEST_PAGE], (SEAL, SEAL_OUT))
    assert out["kept"] == [] and _ids(out["held"]) == ["seal", "plate"]
    assert out["summary"]["requirements_subparts_not_screened"] == 2
    assert "stopped" in out["summary"]
    # the part itself WAS read; only the screen could not run
    assert "could not be reached" in out["summary"]["model_unavailable"]
    assert "requirements_held_scope_not_read" not in out["summary"]


def test_titles_past_the_one_read_are_held_with_the_real_module(store, monkeypatch):
    monkeypatch.setattr(clause_scope, "MAX_TITLES", 3)
    out = gate(flags(), [NEST_PAGE], (SEAL, SEAL_OUT))
    # 1.1, 4.1 and 4.1.1 are screened and none is flagged: the seal is kept;
    # 4.2 (holding the plate) was not screened: held
    assert _ids(out["kept"]) == ["seal"] and _ids(out["held"]) == ["plate"]
    assert out["summary"]["requirements_subparts_not_screened"] == 1


def test_nothing_unscreened_leaves_the_count_out(store):
    out = gate(flags(), [NEST_PAGE], (SEAL, SEAL_OUT))
    assert "requirements_subparts_not_screened" not in out["summary"]
    assert "requirements_kept_sub_headings_not_screened" not in out["summary"]


# ------------------- a start found by shape only holds; a failed screen is counted

TABLE_PAGE = (
    2,
    "Table 4 Weld notes\n"
    + TI_SCOPE
    + "\nThe nameplate shall be of stainless steel.\n",
)
NAMEPLATE = req("plate", 2, "The nameplate shall be of stainless steel.")


def test_a_shape_start_the_model_confirms_is_held_never_excluded(store):
    # the REAL candidate finder proposes "Table 4 Weld notes"; the model says
    # "limited to titanium" and the sheet states carbon steel: before, the
    # nameplate clause was set aside as outside the part; nothing checks that
    # a table title starts a part, so it can only be held
    model = FakeModel(scope=titanium_if_named)
    out = gate(model, [AA_PAGE, TABLE_PAGE], (GENERAL, NAMEPLATE))
    assert out["items"] == [] and _ids(out["kept"]) == ["aa"]
    assert _ids(out["held"]) == ["plate"]
    assert_a_hold_for_the_engineer(out["held"][0]["detail"])
    assert out["summary"]["candidates_read"] == 1


def test_a_failed_title_screen_holds_its_requirements_and_counts_them(store):
    model = flags()
    model.replies["titles"] = lambda prompt: {"nonsense": 1}  # fits no schema
    out = gate(model, [NEST_PAGE], (SEAL, SEAL_OUT))
    assert out["kept"] == [] and _ids(out["held"]) == ["seal", "plate"]
    assert out["summary"]["requirements_subparts_not_screened"] == 2
    assert "stopped" not in out["summary"]  # the model was not down


def test_requirements_placed_only_by_page_are_kept_and_counted_apart(store):
    ghost = req("ghost", 1, "The pump shall be tested before it is dispatched.")
    out = gate(flags(), [NEST_PAGE], (SEAL, ghost))
    assert _ids(out["kept"]) == ["seal", "ghost"]  # kept, never skipped silently
    # the screen ran: this is not a failed read, so it is not "held"
    assert out["summary"]["requirements_kept_sub_headings_not_screened"] == 1
    assert "requirements_subparts_not_screened" not in out["summary"]
    assert out["held"] == []


def test_requirements_placed_only_by_page_are_held_when_the_screen_failed(store):
    ghost = req("ghost", 1, "The pump shall be tested before it is dispatched.")
    model = flags()
    model.replies["titles"] = lambda prompt: {"nonsense": 1}
    out = gate(model, [NEST_PAGE], (SEAL, ghost))
    assert out["kept"] == [] and _ids(out["held"]) == ["seal", "ghost"]
    assert out["summary"]["requirements_subparts_not_screened"] == 2
    assert "requirements_kept_sub_headings_not_screened" not in out["summary"]


def test_requirements_in_a_kept_candidate_start_are_kept_and_counted_apart(stub):
    stub.heads = ["Appendix 9 (jacketed vessels)"]
    out = gate(
        FakeModel(scope=NOT_LIMITED),
        [AA_PAGE, (2, JACKET_PAGE[1])],
        (GENERAL, JACKET | {"page": 2}),
    )
    assert _ids(out["kept"]) == ["aa", "jacket"]
    assert out["summary"]["requirements_kept_sub_headings_not_screened"] == 1
    assert "requirements_subparts_not_screened" not in out["summary"]


def test_a_review_with_the_model_down_holds_every_placed_clause_and_says_so(
    stub, monkeypatch
):
    result, stored, ids = _review(
        monkeypatch, FakeModel(fail="the model could not be reached")
    )
    for name in ("aa", "zz", "tt"):
        assert stored[ids[name]]["state"] == scope_ledger.APPLIES_NOT_CHECKED
        assert stored[ids[name]]["reason_code"] == "applicability_unsure"
        # nothing was compared on it: no finding rests on it
        assert {f["compliance_status"] for f in result["findings"]
                if f.get("requirement_id") == ids[name]} <= HELD_ROW
    counts = result["requirement_split"]["division_scope"]
    assert counts["requirements_held_scope_not_read"] == 3
    assert "could not be reached" in counts["model_unavailable"]
    assert "requirements_in_unread_divisions" not in counts
