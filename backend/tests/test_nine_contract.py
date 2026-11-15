"""The shared shapes of the nine-role review (`nine_contract`): the base the builders write against. Invented data only.

What each test guards: a role that did not run is always named with a reason; a record always holds the nine roles in order; each
role that can spend has its own step name and the checklist keeps the existing one; the shapes cannot be changed after they are made.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from app import agent_claude
from app import nine_contract as nine


def _role(n: int, state: str = "ran", why: str | None = None, **kw) -> nine.RoleRecord:
    return nine.RoleRecord(n, nine.ROLE_NAMES[n], state, why, "code", (), 0, None, **kw)


def _record(roles) -> nine.ReviewRecord:
    return nine.ReviewRecord(
        "run-1", "doc-1", "claude", tuple(roles), (), ("doc-1", "book-1")
    )


def test_there_are_nine_roles_in_the_owners_order():
    assert nine.ROLE_NUMBERS == (1, 2, 3, 4, 5, 6, 7, 8, 9)
    assert [nine.ROLE_NAMES[n] for n in nine.ROLE_NUMBERS] == [
        "Reader", "Project context", "Librarian", "Reviewer", "Checklist", "Second reviewer", "Code", "Decision rule", "Writer",
    ]  # fmt: skip


def test_each_spending_role_has_its_own_step_and_the_code_roles_have_none():
    steps = nine.STEP_OF_ROLE
    assert set(steps) == {
        1,
        2,
        3,
        4,
        5,
        6,
        9,
    }  # 7 Code and 8 Decision rule never call a model
    assert len(set(steps.values())) == len(
        steps
    )  # one cap line per role: no two roles share a step name
    assert all(name and name == name.strip() for name in steps.values())


def test_the_checklist_keeps_the_existing_step_name():
    assert (
        nine.STEP_OF_ROLE[5] == agent_claude.STEP
    )  # the existing batch path is not renamed in the ledger


def test_a_new_record_names_all_nine_roles_as_not_run_with_a_reason():
    record = nine.empty_record("run-1", "doc-1", "automatic")
    assert [r.role_no for r in record.roles] == list(nine.ROLE_NUMBERS)
    assert all(r.state == "not_run" and r.why == nine.NOT_REACHED for r in record.roles)
    assert (
        record.shown_document_ids is None
    )  # no list stored is not the same as an empty list
    assert len(record.not_run()) == 9
    assert record.roles_line().startswith(
        "Roles run: 0 of 9; not run: 1 Reader: not reached; 2 Project context: not reached"
    )


@pytest.mark.parametrize("state", ["not_run", "ran_partly"])
@pytest.mark.parametrize("why", [None, "", "   "])
def test_a_role_that_did_not_run_in_full_must_say_why(state, why):
    with pytest.raises(ValueError, match="gives no reason"):
        _role(2, state, why)


def test_a_role_that_ran_needs_no_reason_and_an_unknown_state_is_refused():
    assert _role(1).why is None
    with pytest.raises(ValueError, match="unknown role state"):
        _role(1, "done")
    with pytest.raises(ValueError, match="is not named"):
        nine.RoleRecord(1, "Writer", "ran", None, "code", (), 0, None)


def test_a_record_must_hold_the_nine_roles_once_each_in_order():
    nine_roles = [_role(n) for n in nine.ROLE_NUMBERS]
    assert _record(nine_roles).not_run() == ()
    for wrong in (
        nine_roles[:8],
        nine_roles[::-1],
        [*nine_roles[:8], _role(8)],
        [*nine_roles, _role(9)],
    ):
        with pytest.raises(ValueError, match="nine roles"):
            _record(wrong)


def test_the_first_sheet_line_names_what_ran_what_ran_partly_and_what_did_not():
    roles = [_role(n) for n in nine.ROLE_NUMBERS]
    roles[1] = _role(2, "not_run", "no project documents are held for this paper")
    roles[3] = _role(4, "ran_partly", "budget reached; 2 chapters not read")
    line = _record(roles).roles_line()
    assert line.startswith(
        "Roles run: 8 of 9: 1 Reader, 3 Librarian, 4 Reviewer (partly), 5 Checklist"
    )
    assert line.endswith(
        "; not run: 2 Project context: no project documents are held for this paper"
    )
    assert (
        _record([_role(n) for n in nine.ROLE_NUMBERS])
        .roles_line()
        .endswith("; not run: none")
    )


def test_a_read_entry_belongs_to_its_own_role_and_a_call_to_a_real_role():
    read = nine.ReadEntry(
        4, "call-1", "book-1", "rule_book", (12, 13), "5", 1, 2, 4200, "ab" * 32, 0
    )
    assert _role(4, reads=(read,)).reads == (read,)
    with pytest.raises(ValueError, match="another role"):
        _role(1, reads=(read,))
    call = nine.CallEntry(
        12,
        "call-1",
        "nine_reviewer",
        "claude",
        "model-x",
        "cd" * 32,
        "sent",
        None,
        None,
        "2026-11-15T00:00:00Z",
    )
    with pytest.raises(ValueError, match="does not exist"):
        nine.ReviewRecord(
            "run-1",
            "doc-1",
            "claude",
            tuple(_role(n) for n in nine.ROLE_NUMBERS),
            (call,),
            None,
        )


def test_the_shapes_are_frozen_and_a_whole_record_is_plain_json():
    shapes = [
        v
        for v in vars(nine).values()
        if dataclasses.is_dataclass(v) and isinstance(v, type)
    ]
    assert len(shapes) >= 18 and all(s.__dataclass_params__.frozen for s in shapes)
    part = nine.ChapterPart(1, 1, 12, 14, 4200, "ab" * 32)
    chapter = nine.Chapter("book-1", "5", 310, 1, 12, 14, 4200, (part,), "heading")
    assert chapter.scanned_pages == 0
    finding = nine.Finding(
        "F-0123456789ab", "R-rule-1", "reviewer", "book-1", "5.2", 13, "on the stated page", False, "Set pressure",
        ("set_pressure",), "TAG-1", 1, "Set pressure 10 bar", "shall not exceed 12 bar", "met", "rule-1", "AI approved",
        ("call-1",), False, (("book-1", "5", 1),),
    )  # fmt: skip
    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.ai_verdict = "not_met"
    read = nine.ReadEntry(
        4,
        "call-1",
        "book-1",
        "rule_book",
        (12, 13, 14),
        "5",
        1,
        1,
        4200,
        part.text_sha256,
        0,
    )
    roles = [_role(n) for n in nine.ROLE_NUMBERS]
    roles[3] = _role(
        4, reads=(read,), produced={"findings": 1, "finding_ids": [finding.finding_id]}
    )
    back = json.loads(json.dumps(dataclasses.asdict(_record(roles))))
    assert (
        back["roles"][3]["reads"][0]["pages"] == [12, 13, 14]
        and back["roles"][3]["produced"]["findings"] == 1
    )
    assert back["shown_document_ids"] == ["doc-1", "book-1"]
