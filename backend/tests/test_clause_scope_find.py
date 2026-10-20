"""Order 161 B: finding the parts of a standard that may limit themselves
(`clause_scope`): candidate starts, sub-heading units, the verified title
screen and the downgrade. Invented standard text only (rule 13): no real
standard, part, material or layout.
"""

from __future__ import annotations

import json
import logging

import pytest

from app import ai_applicability, clause_scope, db, subject_scope
from app.config import settings
from app.reasoning_provider import ProviderRefused, Response

BODY = "The shell shall be 6 mm thick.\n"
PAGE1 = (1, "PART 1\nGENERAL VESSELS\n1.1 SCOPE\nThis Part applies to all vessels.\n")


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "clause_scope.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _text(*pages):
    return subject_scope.StandardText(list(pages))


def _starts(*pages):
    text = _text(*pages)
    return text, clause_scope.candidate_starts(text, ai_applicability.divisions(text))


# ---------------------------------------------------------------- candidates
@pytest.mark.parametrize(
    "heading",
    [
        "SECTION 8",
        "DIVISION 8 WINDOWS",
        "Supplement 8",
        "MANDATORY APPENDIX 8-1",
        "APPENDIX 8.1",
        "APPENDIX 12-A",
        "Appendix 3-2",
        "Annex A-1",
        "Appendix 8 -- Window Rules",
        "Appendix 8. Window Rules",
    ],
)
def test_heading_shapes_outside_the_division_finder_are_proposed(heading):
    text, found = _starts(PAGE1, (2, f"{heading}\nWINDOW RULES\n{BODY}"))
    assert [(c["heading"], c["kind"]) for c in found] == [(heading, "shape")]
    assert found[0]["at"] == text.offsets[found[0]["line"]]
    assert ai_applicability.divisions(text)[-1]["name"] != ("part", "8")


def test_a_break_the_division_finder_makes_is_a_candidate():
    page = (2, f"APPENDIX 8\nWINDOWS\n{BODY}APPENDIX 9\nSEALS\n{BODY}")
    text, found = _starts(PAGE1, page)
    assert [d["name"] for d in ai_applicability.divisions(text)] == [
        ("part", "1"),
        None,
        None,
    ]
    assert [(c["heading"], c["kind"]) for c in found] == [
        ("APPENDIX 8", "break"),
        ("APPENDIX 9", "break"),
    ]


def test_a_heading_in_the_middle_of_a_page_is_a_break_candidate():
    lines = "".join(f"Rule {n} about nozzles is given here.\n" for n in range(8))
    _, found = _starts(PAGE1, (2, lines + "APPENDIX 8\nWINDOWS\n" + BODY))
    assert [(c["heading"], c["kind"]) for c in found] == [("APPENDIX 8", "break")]


def test_not_proposed_when_known_running_contents_or_prose():
    contents = (
        3,
        "SECTION 8 Windows 45\nSECTION 9 Seals ........ 51\nSECTION 7 Seals 4.5\n"
        + BODY,
    )
    prose = (
        4,
        "Notes\nThe design pressure 10 bar is used for all of the checks "
        "listed in this table of values\n" + BODY,
    )
    running = [(n, f"Vessel Code {n}\nSECTION 5\n{BODY}") for n in range(5, 10)]
    text, found = _starts(PAGE1, contents, prose, *running)
    heads = [c["heading"] for c in found]
    assert not any("SECTION 8" in h or "SECTION 9" in h for h in heads)
    assert not any(h.startswith("The design") for h in heads)
    assert not any(h.startswith("Vessel Code") for h in heads)
    # "SECTION 5" heads every page 5-9: a repeated page head is proposed once
    # per page at most, and never a division twice
    divs = ai_applicability.divisions(text)
    assert all(c["line"] not in {d["line"] for d in divs if d["name"]} for c in found)


def test_a_long_line_of_the_shape_is_not_proposed():
    long_line = "Section 8 " + "and the rules about the window frames " * 2
    _, found = _starts(PAGE1, (2, f"{long_line}\n{BODY}"))
    assert found == []


def test_a_contents_page_proposes_nothing():
    rows = "".join(f"SECTION {n}\n" for n in range(1, 8))
    _, found = _starts(PAGE1, (2, rows))
    assert found == []


def test_a_named_division_is_not_proposed():
    _, found = _starts(PAGE1, (2, f"APPENDIX 8\nWINDOW RULES\n{BODY}"))
    assert found == []


# ------------------------------------------------------------- sub-headings
SUB = (
    1,
    "PART 1\nGENERAL VESSELS\n"
    "4.1 General rules\nThe shell shall be 6 mm thick.\n"
    "4.2 Acrylic windows\nA window shall last 10 years.\nA window shall be clear.\n"
    "4.3 Seals\nA seal shall be soft.\n",
)


def _line(text, needle):
    return next(i for i, line in enumerate(text.lines) if needle in line)


def test_units_hold_only_the_headings_with_a_wanted_line_and_stop_at_the_next():
    text = _text(SUB)
    div = ai_applicability.divisions(text)[0]
    units = clause_scope.subclause_units(text, div, None, [_line(text, "10 years")])
    assert [u["title"] for u in units] == ["4.2 Acrylic windows"]
    unit = units[0]
    assert unit["line"] == _line(text, "4.2 Acrylic")
    assert unit["at"] == text.offsets[unit["line"]]
    assert unit["end"] == text.offsets[_line(text, "4.3 Seals")]
    both = [_line(text, "10 years"), _line(text, "soft")]
    titles = [u["title"] for u in clause_scope.subclause_units(text, div, None, both)]
    assert titles == ["4.2 Acrylic windows", "4.3 Seals"]
    assert clause_scope.subclause_units(text, div, None, []) == []


def test_units_never_pass_the_end_of_the_division():
    text = _text(SUB)
    div = ai_applicability.divisions(text)[0]
    stop = _line(text, "4.3 Seals")
    soft = [_line(text, "soft")]
    assert clause_scope.subclause_units(text, div, stop, soft) == []
    units = clause_scope.subclause_units(text, div, stop, [_line(text, "10 years")])
    assert units[0]["end"] <= text.offsets[stop]


def test_units_are_capped_and_one_per_title():
    many = "".join(
        f"4.{n} Item {chr(97 + n % 26)}{chr(97 + n // 26)}\nRule {n} shall hold.\n"
        for n in range(1, 80)
    )
    text = _text((1, "PART 1\nGENERAL VESSELS\n" + many))
    div = ai_applicability.divisions(text)[0]
    wanted = [i for i, line in enumerate(text.lines) if line.startswith("Rule")]
    units = clause_scope.subclause_units(text, div, None, wanted)
    assert len(units) == clause_scope.MAX_TITLES
    twin = _text(
        (1, "PART 1\nGENERAL VESSELS\n4.1 Seals\nA shall.\n4.1 Seals\nB shall.\n")
    )
    wanted = [_line(twin, "A shall"), _line(twin, "B shall")]
    div = ai_applicability.divisions(twin)[0]
    assert len(clause_scope.subclause_units(twin, div, None, wanted)) == 1


# ------------------------------------------------------------ title screen
class Titles:
    """A model that returns the given titles; counts its calls."""

    requested_model = "test-model"

    def __init__(self, titles=None, fail=None):
        self.titles, self.fail, self.prompts = titles or [], fail, []

    def reason(self, packet):
        self.prompts.append(packet.prompt)
        if self.fail:
            raise ProviderRefused(self.fail)
        return Response(
            text=json.dumps({"titles": self.titles}),
            provider="ollama",
            model_tag="test-model",
            digest="d",
            finish_reason="stop",
            prompt_sha256=packet.sha256,
        )


UNITS = [
    {"line": 4, "at": 10, "end": 50, "title": "4.2 Acrylic windows"},
    {"line": 8, "at": 50, "end": 90, "title": "4.3 Seals"},
]


def test_a_verbatim_flagged_title_is_kept(temp_storage):
    model = Titles(["4.2 Acrylic windows"])
    assert clause_scope.screen_titles(UNITS, model, {}) == [UNITS[0]]
    assert model.prompts[0].endswith("4.2 Acrylic windows\n4.3 Seals\n")


def test_an_invented_title_is_never_kept(temp_storage):
    model = Titles(["4.2 Acrylic windows", "4.9 Bronze castings"])
    assert clause_scope.screen_titles(UNITS, model, {}) == []
    assert len(model.prompts) == 2  # the reply was rejected and asked again


def test_code_ignores_an_invented_title_even_when_the_task_check_is_off(
    temp_storage, monkeypatch
):
    unchecked = ai_applicability.ai_task_runner.TaskSpec(
        name="subclause_scope_unchecked",
        version="v1",
        instruction=clause_scope.SUBSCOPE_INSTRUCTION,
        schema=clause_scope.SUBSCOPE_SCHEMA,
    )
    monkeypatch.setattr(clause_scope, "SUBSCOPE_TASK", unchecked)
    model = Titles(["4.9 Bronze castings", "Acrylic windows", "4.3 SEALS"])
    assert clause_scope.screen_titles(UNITS, model, {}) == [UNITS[1]]


def test_a_failed_or_stopped_read_flags_nothing(temp_storage):
    assert clause_scope.screen_titles(UNITS, Titles(fail="offline"), {}) == []
    model = Titles(["4.3 Seals"])
    assert clause_scope.screen_titles(UNITS, model, {"stopped": "x"}) == []
    assert model.prompts == []
    fresh = Titles(["4.3 Seals"])
    assert clause_scope.screen_titles([], fresh, {}) == []
    assert fresh.prompts == []


def test_the_task_is_registered_and_logs_no_text(temp_storage, caplog):
    assert clause_scope.SUBSCOPE_TASK.name == "subclause_scope"
    with caplog.at_level(logging.DEBUG):
        clause_scope.screen_titles(UNITS, Titles(["4.3 Seals"]), {})
    assert "Seals" not in caplog.text


# --------------------------------------------------------------- downgrade
@pytest.mark.parametrize(
    ("verdict", "result"),
    [
        ("does_not_apply", "held"),
        ("held", "held"),
        ("kept", "kept"),
        ("applies", "kept"),
        (None, "kept"),
    ],
)
def test_downgrade_can_only_hold(verdict, result):
    assert clause_scope.downgrade(verdict) == result
