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
from app import ai_applicability, scope_ledger, subject_scope
from app.config import settings
from tests.test_141_division_scope import (  # noqa: F401 - temp_storage is a fixture
    GENERAL,
    GRAPHITE,
    LIMITED,
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

    def subclause_units(self, text, div, end, wanted_lines):
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


def test_requirements_beyond_the_limit_are_kept_and_counted(stub):
    model = FakeModel()
    out = gate(model, PAGES, (GENERAL, SPECIAL, TITAN), limit=1)
    assert _ids(out["kept"]) == ["aa", "zz", "tt"] and out["items"] == []
    summary = out["summary"]
    assert summary["requirements_beyond_limit"] == 2
    assert summary["requirements_gated"] == 3 and summary["not_read_limit"] == 2
    assert model.calls == ["division"]  # one read: the limit is the run's, not a part's
    # a count of none is left out, never shown as 0
    assert "requirements_in_unread_divisions" not in summary
    assert "requirements_unplaced" not in summary


def test_requirements_of_parts_nobody_could_read_are_kept_and_counted(stub):
    out = gate(
        FakeModel(fail="the model could not be reached"),
        PAGES,
        (GENERAL, SPECIAL, TITAN),
    )
    assert _ids(out["kept"]) == ["aa", "zz", "tt"] and out["held"] == []
    assert out["summary"]["requirements_in_unread_divisions"] == 3
    assert out["summary"]["requirements_gated"] == 3
    assert "requirements_beyond_limit" not in out["summary"]


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
def test_a_part_with_a_heading_of_another_shape_is_read_and_decided(stub, heading):
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
    assert _ids(out["items"]) == ["weld"] and _ids(out["kept"]) == ["aa"]
    assert out["summary"]["candidates_read"] == 1


def test_a_heading_in_the_middle_of_a_page_is_read_not_skipped(stub):
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
    assert _ids(out["items"]) == ["tt"] and _ids(out["kept"]) == ["aa"]


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
    assert not any(f.get("requirement_id") == ids["zz"] for f in result["findings"])
    counts = result["requirement_split"]["division_scope"]
    assert counts["requirements_held_unsure"] == 1
    assert counts["requirements_gated"] == 3


def test_a_review_with_the_reader_off_stores_no_counts(stub, monkeypatch):
    model = FakeModel(scope=UNSURE)
    result, stored, ids = _review(monkeypatch, model, enabled=False)
    assert {stored[i]["state"] for i in ids.values()} == {scope_ledger.CHECKED}
    assert model.calls == [] and "division_scope" not in result["requirement_split"]
    assert settings.ai_division_scope_enabled is False
