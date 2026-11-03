"""#805 rule boxes: label, check and second check of compiled rules on a copy. Invented standards text, an injected
transport: nothing leaves."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from app import claude_spend, db
from app.config import settings
from tests.test_1584_standards_compiler import (
    _document,
    lane,  # noqa: F401
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import rule_boxes as cli
from rule_box_tools import (
    rule_box_check,
    rule_box_fieldfirst,
    rule_box_fields,
    rule_box_judge,
    rule_box_run,
    rule_box_scope,
)
from rule_box_tools import rule_box_labels as rule_boxes

DOC, LABEL = "std-box", "SAES-Z-910"
Q_NUM = "The invented design pressure shall not exceed 10 bar."
Q_LIST = "The invented body material shall not be cast iron."
Q_SENT = "The invented marking shall be legible from two metres."
Q_COND = "Where the invented service is gas, the design temperature shall be at least 20 degC."


def _put(conn, rid, quote, n, **over):
    row = {
        "id": rid,
        "standard_document_id": DOC,
        "clause": f"4.{n}",
        "page": 1,
        "quote_start": n,
        "quote": quote,
        "field": "design pressure",
        "comparator": None,
        "limit_value": None,
        "unit": None,
        "condition_text": None,
        "exception_text": None,
    }
    row.update(over)
    cols = ",".join(row)
    conn.execute(
        f"INSERT INTO compiled_rules ({cols}) VALUES ({','.join('?' * len(row))})",
        list(row.values()),
    )


@pytest.fixture
def rules(lane, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    _document(DOC, LABEL, pages=("Invented standard.",))
    conn = db.connect()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS compiled_rules (id TEXT PRIMARY KEY, standard_document_id TEXT, clause TEXT,"
        " page INT, quote_start INT, quote TEXT, field TEXT, comparator TEXT, limit_value REAL, unit TEXT,"
        " condition_text TEXT, exception_text TEXT, applies_to TEXT)"
    )
    with conn:
        _put(conn, "r1", Q_NUM, 1, comparator="<=", limit_value=10.0, unit="bar")
        _put(conn, "r2", Q_LIST, 2, field="body material")
        _put(conn, "r3", Q_SENT, 3, field="marking")
    rule_boxes.ensure_schema(conn)
    rule_box_check.ensure_schema(conn)
    return conn


def _gate_open(doc, label):
    return None


class Fake:
    """The Messages transport. `answer(prompt) -> reply text`."""

    def __init__(self, answer, usage=None):
        self.answer, self.bodies = answer, []
        self.usage = usage or {"input_tokens": 100, "output_tokens": 50}

    def __call__(self, url, *, headers, body, timeout):
        self.bodies.append(body)
        text = self.answer(body["messages"][0]["content"])
        return {
            "model": body["model"],
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": text}],
            "usage": self.usage,
        }


def _labels(prompt):
    out = []
    for n in range(1, 4):
        if f"{n}. [" not in prompt:
            continue
        line = next(x for x in prompt.splitlines() if x.startswith(f"{n}. ["))
        box = "a" if "design pressure" in line else "b" if "marking" in line else "a"
        out.append(
            {
                "i": n,
                "document_kind": "datasheet",
                "equipment_type": "pressure vessel",
                "box": box,
                "document_name": None,
            }
        )
    return json.dumps(out)


# ------------------------------------------------------------------------------------------ step 1: shape check
@pytest.mark.parametrize(
    "record, reason",
    [
        (
            {
                "i": 1,
                "document_kind": "datasheet",
                "equipment_type": "pump",
                "box": "z",
                "document_name": None,
            },
            "box_not_in_set",
        ),
        (
            {
                "i": 1,
                "document_kind": "banana",
                "equipment_type": "pump",
                "box": "a",
                "document_name": None,
            },
            "document_kind_not_in_list",
        ),
        (
            {
                "i": 1,
                "document_kind": "datasheet",
                "equipment_type": "banana",
                "box": "a",
                "document_name": None,
            },
            "equipment_type_not_in_list",
        ),
        (
            {
                "i": 1,
                "document_kind": "datasheet",
                "equipment_type": "pump",
                "box": "d",
                "document_name": None,
            },
            "box_d_without_a_document_name",
        ),
        (
            {
                "i": 1,
                "document_kind": "datasheet",
                "equipment_type": "pump",
                "box": "d",
                "document_name": "<script>x</script>",
            },
            "box_d_without_a_document_name",
        ),
        (
            {
                "i": 1,
                "document_kind": "datasheet",
                "equipment_type": "pump",
                "box": "a",
                "document_name": "a drawing",
            },
            "name_on_a_box_that_needs_none",
        ),
        (
            {
                "i": 2,
                "document_kind": "datasheet",
                "equipment_type": "pump",
                "box": "a",
                "document_name": None,
            },
            "wrong_index",
        ),
    ],
)
def test_a_label_of_the_wrong_shape_is_not_kept(record, reason):
    assert rule_boxes.verify(record, 1) == (None, reason)


def test_a_box_d_label_keeps_its_document_name_and_nothing_else_is_free_text():
    clean, why = rule_boxes.verify(
        {
            "i": 1,
            "document_kind": "any",
            "equipment_type": "general",
            "box": "d",
            "document_name": "  piping  isometric drawing ",
        },
        1,
    )
    assert why is None and clean["needs_document_name"] == "piping isometric drawing"


def test_every_label_is_stored_once_and_a_second_run_asks_nothing(rules):
    jobs, members, counts = rule_boxes.jobs(rules, _gate_open, per_prompt=2)
    assert (counts["rules_to_label"], counts["prompts"]) == (3, 2)
    fake = Fake(_labels)
    apply = rule_boxes.storer(rules, members, "claude-haiku-4-5")
    report = rule_box_run.run(
        jobs,
        model="claude-haiku-4-5",
        step_prefix="rule_box_label",
        version=rule_boxes.PROMPT_VERSION,
        apply=apply,
        send=fake,
    )
    assert (
        report["status"] == "done" and report["stored"] == 2 and len(fake.bodies) == 2
    )
    rows = rules.execute(
        f"SELECT rule_id, box, model, prompt_version FROM {rule_boxes.TABLE} ORDER BY rule_id"
    ).fetchall()
    assert [(r["rule_id"], r["box"]) for r in rows] == [
        ("r1", "a"),
        ("r2", "a"),
        ("r3", "b"),
    ]
    assert {r["model"] for r in rows} == {"claude-haiku-4-5"} and {
        r["prompt_version"] for r in rows
    } == {rule_boxes.PROMPT_VERSION}
    again, _m, counts = rule_boxes.jobs(rules, _gate_open, per_prompt=2)
    assert again == [] and counts["rules_to_label"] == 0


def test_a_reply_with_one_bad_record_stores_the_good_ones_and_leaves_the_bad_one_for_next_time(
    rules,
):
    def reply(prompt):
        data = json.loads(_labels(prompt))
        data[0]["box"] = "zz"
        return json.dumps(data)

    jobs, members, _c = rule_boxes.jobs(rules, _gate_open, per_prompt=3)
    apply = rule_boxes.storer(rules, members, "m")
    report = rule_box_run.run(
        jobs,
        model="claude-haiku-4-5",
        step_prefix="s",
        version="v",
        apply=apply,
        send=Fake(reply),
    )
    assert report["status"] == "partial" and report["rejected_by_code"] == 1
    assert apply.tally["records_stored"] == 2 and apply.tally["rejected_by_reason"] == {
        "box_not_in_set": 1
    }
    assert [r["id"] for r in rule_boxes.todo(rules)] == ["r1"]


def test_a_reply_that_is_not_a_list_stores_nothing(rules):
    jobs, members, _c = rule_boxes.jobs(rules, _gate_open, per_prompt=3)
    apply = rule_boxes.storer(rules, members, "m")
    rule_box_run.run(
        jobs,
        model="claude-haiku-4-5",
        step_prefix="s",
        version="v",
        apply=apply,
        send=Fake(lambda p: "not json"),
    )
    assert rules.execute(f"SELECT COUNT(*) FROM {rule_boxes.TABLE}").fetchone()[0] == 0


# ------------------------------------------------------------------------------------------ the lane
def test_the_run_stops_cleanly_at_a_cap_and_keeps_what_it_has(rules, monkeypatch):
    jobs, members, _c = rule_boxes.jobs(rules, _gate_open, per_prompt=1)
    assert len(jobs) == 3
    one = rule_box_run.worst_of("claude-haiku-4-5", jobs[0])
    monkeypatch.setattr(
        settings, "claude_budget_usd_per_step", one * 1.5
    )  # room for one call only
    apply = rule_boxes.storer(rules, members, "m")
    fake = Fake(
        _labels, usage={"input_tokens": 100, "output_tokens": 100_000}
    )  # the first call spends the room
    report = rule_box_run.run(
        jobs,
        model="claude-haiku-4-5",
        step_prefix="s",
        version="v",
        apply=apply,
        send=fake,
        workers=1,
    )
    assert report["status"] == "stopped" and report["stop_reason"] == "BudgetExceeded"
    assert len(fake.bodies) == 1 and report["stored"] == 1


def test_a_group_is_packed_under_the_cap_and_each_group_is_its_own_step(rules):
    jobs, _m, _c = rule_boxes.jobs(rules, _gate_open, per_prompt=1)
    each = rule_box_run.worst_of("claude-haiku-4-5", jobs[0])
    packed, too_big = rule_box_run.groups("claude-haiku-4-5", jobs, cap=each * 2.5)
    assert [len(g) for g in packed] == [2, 1] and too_big == []
    _p, big = rule_box_run.groups("claude-haiku-4-5", jobs, cap=each / 2)
    assert len(big) == 3
    fake = Fake(_labels)
    apply = rule_boxes.storer(rules, _m, "m")
    rule_box_run.run(
        jobs,
        model="claude-haiku-4-5",
        step_prefix="rule_box_label",
        version="v",
        apply=apply,
        send=fake,
        cap=each * 2.5,
    )
    steps = {e["step"] for e in claude_spend.entries()}
    assert len(steps) == 2 and all(s.startswith("rule_box_label:") for s in steps)


def test_a_load_error_is_tried_again_and_a_dead_call_is_counted_not_fatal(rules):
    import httpx

    calls = {"n": 0}

    def flaky(url, *, headers, body, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            request = httpx.Request("POST", url)
            raise httpx.HTTPStatusError(
                "x", request=request, response=httpx.Response(529, request=request)
            )
        return Fake(_labels)(url, headers=headers, body=body, timeout=timeout)

    jobs, members, _c = rule_boxes.jobs(rules, _gate_open, per_prompt=3)
    apply = rule_boxes.storer(rules, members, "m")
    report = rule_box_run.run(
        jobs,
        model="claude-haiku-4-5",
        step_prefix="s",
        version="v",
        apply=apply,
        send=flaky,
        sleep=lambda s: None,
    )
    assert report["stored"] == 1 and report["failed"] == 0 and calls["n"] == 2


def test_a_standard_the_gate_refuses_is_not_sent_and_is_counted(rules):
    jobs, _m, counts = rule_boxes.jobs(
        rules, lambda doc, label: "NotApproved", per_prompt=3
    )
    assert (
        jobs == []
        and counts["rules_in_refused_standards"] == 3
        and counts["standards_refused_by_reason"] == {"NotApproved": 1}
    )


def test_a_document_off_the_approved_list_is_refused_where_every_call_reserves(rules):
    path = __import__("app.claude_approved", fromlist=["x"]).list_path()
    path.write_text(json.dumps({"documents": []}))
    jobs, members, _c = rule_boxes.jobs(rules, _gate_open, per_prompt=3)
    fake = Fake(_labels)
    report = rule_box_run.run(
        jobs,
        model="claude-haiku-4-5",
        step_prefix="s",
        version="v",
        apply=rule_boxes.storer(rules, members, "m"),
        send=fake,
    )
    assert fake.bodies == [] and report["status"] == "stopped"


def test_the_dry_report_prints_the_worst_case_and_sends_nothing(rules):
    jobs, _m, counts = rule_boxes.jobs(rules, _gate_open, per_prompt=2)
    report = cli.dry_report("label", "claude-haiku-4-5", jobs, counts)
    assert (
        report["status"] == "dry" and report["prompts"] == 2 and report["groups"] == 1
    )
    assert (
        0
        < report["typical_estimate_usd"]
        < report["worst_case_usd"]
        <= rule_box_run.GROUP_CAP_USD
    )
    assert claude_spend.entries() == []


def test_a_send_is_refused_unless_the_process_names_this_engine(rules, monkeypatch):
    monkeypatch.delenv(cli.ENGINE_ENV, raising=False)
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    assert cli.lane_refusal() is not None
    monkeypatch.setenv(cli.ENGINE_ENV, "claude")
    assert cli.lane_refusal() is None


# ------------------------------------------------------------------------------------------ step 2
FIELDS = rule_box_check.fields_for("pressure vessel")


def _row(rules, rid):
    return rules.execute("SELECT * FROM compiled_rules WHERE id = ?", (rid,)).fetchone()


def _good_number(**over):
    answer = {
        "field_role": "design_pressure",
        "kind": "number",
        "op": "<=",
        "limit": "10",
        "unit": "bar",
        "values": [],
        "condition": None,
        "subject": "design pressure",
        "quote": "shall not exceed 10 bar",
        "pass_case": {"value": "8", "unit": "bar"},
        "fail_case": {"value": "12", "unit": "bar"},
        "reason": None,
    }
    answer.update(over)
    return answer


def test_a_good_number_check_is_checked_and_both_cases_ran(rules):
    check, reason, status = rule_box_check.verify_check(
        _row(rules, "r1"), _good_number(), FIELDS
    )
    assert (status, reason) == ("checked", None)
    assert (
        check["limit"] == "10"
        and check["pass_case"] == ("8", "bar")
        and check["fail_case"] == ("12", "bar")
    )


def test_a_case_in_another_unit_runs_on_the_existing_conversion(rules):
    answer = _good_number(
        pass_case={"value": "100", "unit": "psi"},
        fail_case={"value": "200", "unit": "psi"},
    )
    assert (
        rule_box_check.verify_check(_row(rules, "r1"), answer, FIELDS)[2] == "checked"
    )


@pytest.mark.parametrize(
    "over, reason",
    [
        ({"limit": "11"}, "limit_not_in_quote"),
        ({"unit": "psi"}, "unit_not_in_quote"),
        ({"op": ">="}, "comparator_not_in_quote"),
        ({"quote": "shall never exceed 10 bar"}, "quote_not_in_rule"),
        ({"field_role": "no_such_field"}, "role_not_on_type"),
        ({"pass_case": {"value": "12", "unit": "bar"}}, "pass_case_fails"),
        ({"fail_case": {"value": "8", "unit": "bar"}}, "fail_case_passes"),
        ({"pass_case": None}, "test_case_missing"),
        ({"fail_case": {"value": "12", "unit": "degC"}}, "test_unit_not_the_quantity"),
        ({"fail_case": {"value": "lots", "unit": "bar"}}, "test_value_not_a_number"),
        ({"condition": "when it rains"}, "condition_not_in_rule"),
        ({"kind": "table"}, "kind_not_allowed"),
    ],
)
def test_a_number_check_code_cannot_verify_is_a_failed_check(rules, over, reason):
    check, why, status = rule_box_check.verify_check(
        _row(rules, "r1"), _good_number(**over), FIELDS
    )
    assert (check, status) == (None, "failed check") and why == reason


def test_a_limit_that_is_not_the_one_the_compiler_stored_is_a_failed_check(rules):
    rules.execute("UPDATE compiled_rules SET limit_value = 12 WHERE id = 'r1'")
    assert (
        rule_box_check.verify_check(_row(rules, "r1"), _good_number(), FIELDS)[1]
        == "differs_from_compiled_limit"
    )


def test_an_unreadable_reply_and_a_model_that_declines_are_not_checks(rules):
    assert rule_box_check.verify_check(_row(rules, "r1"), None, FIELDS)[1:] == (
        "reply_unreadable",
        "failed check",
    )
    declined = {"field_role": None, "kind": None, "reason": "no_single_value"}
    assert rule_box_check.verify_check(_row(rules, "r1"), declined, FIELDS)[1:] == (
        "no_single_value",
        "no typed check",
    )


def test_a_list_check_is_verified_and_both_cases_run(rules):
    answer = {
        "field_role": "body_material",
        "kind": "list",
        "op": "is_not",
        "values": ["cast iron"],
        "subject": "body material",
        "quote": "shall not be cast iron",
        "pass_case": {"value": "carbon steel"},
        "fail_case": {"value": "cast iron"},
    }
    fields = {"body_material": "text"}
    check, reason, status = rule_box_check.verify_check(
        _row(rules, "r2"), answer, fields
    )
    assert (status, reason) == ("checked", None) and check["values"] == ["cast iron"]
    bad = {**answer, "values": ["ductile iron"]}
    assert (
        rule_box_check.verify_check(_row(rules, "r2"), bad, fields)[1]
        == "value_not_in_quote"
    )
    swapped = {
        **answer,
        "pass_case": {"value": "cast iron"},
        "fail_case": {"value": "carbon steel"},
    }
    assert (
        rule_box_check.verify_check(_row(rules, "r2"), swapped, fields)[1]
        == "pass_case_fails"
    )


def test_a_rule_of_a_type_without_a_field_list_is_marked_and_not_asked_and_a_box_b_rule_is_stored_by_kind(
    rules,
):
    with rules:
        for rid, box, eq in (
            ("r1", "a", "pump"),
            ("r2", "a", "boiler"),
            ("r3", "b", "boiler"),
        ):
            rules.execute(
                f"INSERT INTO {rule_boxes.TABLE} VALUES (?,?,?,?,NULL,'m','v','t',NULL)",
                (rid, "datasheet", eq, box),
            )
    assert (
        rule_box_check.fields_for("pump")
        and rule_box_check.fields_for("boiler") is None
    )
    counts = rule_box_check.settle_without_a_call(rules)
    assert counts == {
        "stored by kind": 1,
        "field list to confirm": 1,
        "not_decidable_from_a_datasheet": 0,
        "scoped: judge at review time": 0,
        "stored for review of that kind": 0,
    }
    states = dict(
        rules.execute(f"SELECT rule_id, status FROM {rule_box_check.CHECKS}").fetchall()
    )
    assert states == {"r2": "field list to confirm", "r3": "stored by kind"}
    assert [r["id"] for r in rule_box_check.check_todo(rules)] == ["r1"]


def test_step_two_asks_one_rule_per_prompt_and_stores_the_check_with_the_model(rules):
    with rules:
        rules.execute(
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r1','datasheet','pressure vessel','a',NULL,'h','v','t',NULL)"
        )
        rules.execute(
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r3','datasheet','pressure vessel','a',NULL,'h','v','t',NULL)"
        )
    rules.execute(
        "UPDATE compiled_rules SET quote = 'The invented test pressure shall be at least 15 bar.' WHERE id = 'r3'"
    )
    jobs, members, counts = rule_box_check.check_jobs(rules, _gate_open)
    assert counts["prompts"] == 2 and all(len(j.prompt) < 6000 for j in jobs)
    assert Q_NUM in jobs[0].prompt and Q_SENT not in jobs[0].prompt

    def reply(prompt):
        return json.dumps(
            _good_number()
            if Q_NUM in prompt
            else {"field_role": None, "kind": None, "reason": "no_single_value"}
        )

    apply = rule_box_check.check_storer(rules, members, "claude-sonnet-5-5")
    report = rule_box_run.run(
        jobs,
        model="claude-sonnet-5-5",
        step_prefix="c",
        version="v",
        apply=apply,
        send=Fake(reply),
    )
    assert (
        report["asked"] == 2
        and apply.tally["checked"] == 1
        and apply.tally["no_typed_check"] == 1
    )
    row = rules.execute(
        f"SELECT * FROM {rule_box_check.CHECKS} WHERE rule_id='r1'"
    ).fetchone()
    assert (
        row["status"],
        row["field_role"],
        row["limit_text"],
        row["unit"],
        row["model"],
    ) == ("checked", "design_pressure", "10", "bar", "claude-sonnet-5-5")
    assert row["prompt_version"] == rule_box_check.CHECK_VERSION and json.loads(
        row["pass_json"]
    ) == ["8", "bar"]


# ------------------------------------------------------------------------------------------ step 3
CHECK = {
    "kind": "number",
    "field_role": "design_pressure",
    "limit": "10",
    "unit": "bar",
    "values": [],
}
SECOND = {"box": "a", "field_role": "design_pressure", "limit": "10.0", "unit": "BAR"}


def test_the_second_check_agrees_only_when_all_four_match_after_normalising():
    ok, differs, _s = rule_box_check.agree("a", CHECK, SECOND)
    assert ok and differs == []
    for key, wrong in (
        ("box", "c"),
        ("field_role", "test_pressure"),
        ("limit", "12"),
        ("unit", "psi"),
    ):
        ok, differs, _s = rule_box_check.agree("a", CHECK, {**SECOND, key: wrong})
        assert not ok and differs == [key]
    assert rule_box_check.agree("a", CHECK, None)[0] is False
    assert rule_box_check.agree("a", CHECK, {**SECOND, "limit": None})[1] == ["limit"]


def test_a_list_rule_agrees_on_the_same_words_in_any_order():
    check = {
        "kind": "list",
        "field_role": "body_material",
        "limit": None,
        "unit": None,
        "values": ["Cast Iron", "Bronze"],
    }
    second = {
        "box": "a",
        "field_role": "body_material",
        "limit": "bronze | cast iron",
        "unit": None,
    }
    assert rule_box_check.agree("a", check, second)[0]
    assert not rule_box_check.agree("a", check, {**second, "limit": "bronze"})[0]


def test_step_three_uses_a_fresh_prompt_that_shows_no_earlier_answer_and_never_the_same_model(
    rules,
):
    with rules:
        rules.execute(
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r1','datasheet','pressure vessel','a',NULL,'h','v','t',NULL)"
        )
    jobs, members, _c = rule_box_check.check_jobs(rules, _gate_open)
    rule_box_run.run(
        jobs,
        model="claude-sonnet-5-5",
        step_prefix="c",
        version="v",
        apply=rule_box_check.check_storer(rules, members, "claude-sonnet-5-5"),
        send=Fake(lambda p: json.dumps(_good_number())),
    )
    same, _m, counts = rule_box_check.second_jobs(
        rules, _gate_open, "claude-sonnet-5-5"
    )
    assert same == [] and counts["rules_whose_check_used_this_model"] == 1
    jobs, members, _c = rule_box_check.second_jobs(
        rules, _gate_open, "claude-haiku-5-5"
    )
    assert len(jobs) == 1
    prompt = jobs[0].prompt
    assert (
        Q_NUM in prompt
        and "design_pressure_value" not in prompt
        and "shall not exceed 10 bar" not in prompt.split("THE REQUIREMENT")[0]
    )
    assert '"limit": "10"' not in prompt and "pass_case" not in prompt
    apply = rule_box_check.second_storer(rules, members, "claude-haiku-5-5")

    def reply(prompt):
        return json.dumps(
            {"box": "a", "field_role": "design_pressure", "limit": "10", "unit": "bar"}
        )

    report = rule_box_run.run(
        jobs,
        model="claude-haiku-5-5",
        step_prefix="s",
        version="v",
        apply=apply,
        send=Fake(reply),
    )
    assert apply.tally["agreed"] == 1 and report["stored"] == 1
    assert (
        rule_box_check.advanced(rules) == 0
    )  # agreement alone no longer advances: the identity check is needed
    row = rules.execute(
        f"SELECT agree, model, prompt_version FROM {rule_box_check.SECOND}"
    ).fetchone()
    assert tuple(row) == (1, "claude-haiku-5-5", rule_box_check.SECOND_VERSION)


def test_a_disagreeing_rule_does_not_advance(rules):
    with rules:
        rules.execute(
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r1','datasheet','pressure vessel','a',NULL,'h','v','t',NULL)"
        )
    jobs, members, _c = rule_box_check.check_jobs(rules, _gate_open)
    rule_box_run.run(
        jobs,
        model="claude-sonnet-5-5",
        step_prefix="c",
        version="v",
        apply=rule_box_check.check_storer(rules, members, "claude-sonnet-5-5"),
        send=Fake(lambda p: json.dumps(_good_number())),
    )
    jobs, members, _c = rule_box_check.second_jobs(
        rules, _gate_open, "claude-haiku-5-5"
    )
    apply = rule_box_check.second_storer(rules, members, "claude-haiku-5-5")

    def wrong(prompt):
        return json.dumps(
            {"box": "a", "field_role": "design_pressure", "limit": "12", "unit": "bar"}
        )

    rule_box_run.run(
        jobs,
        model="claude-haiku-5-5",
        step_prefix="s",
        version="v",
        apply=apply,
        send=Fake(wrong),
    )
    assert apply.tally["differs"] == 1 and rule_box_check.advanced(rules) == 0


def test_the_second_model_is_never_the_reasoning_model():
    assert rule_box_check.second_model() != settings.claude_reasoning_model


# ------------------------------------------------------------------------------------------ field lists
def _cfihos(tmp_path):
    import csv

    def write(name, header, rows):
        with (tmp_path / f"CFIHOS CORE {name} v2.0.csv").open(
            "w", encoding="cp1252", newline=""
        ) as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)

    for table in ("equipment class", "tag class"):
        write(
            table,
            [f"parent {table} name", "code", f"{table} name"],
            [
                ["rotating", "c1", "invented gizmo"],
                ["invented gizmo", "c2", "small invented gizmo"],
            ],
        )
    write(
        "equipment class property",
        [
            "equipment class CFIHOS unique code",
            "equipment class name",
            "property CFIHOS unique code",
            "property name",
        ],
        [
            ["c1", "invented gizmo", "p1", "gizmo rated flow"],
            ["c2", "small invented gizmo", "p2", "gizmo casing material"],
        ],
    )
    write(
        "tag class property",
        [
            "tag class CFIHOS unique code",
            "tag class name",
            "property CFIHOS unique code",
            "property name",
        ],
        [["c1", "invented gizmo", "p1", "gizmo rated flow"]],
    )
    write(
        "property",
        [
            "CFIHOS unique code",
            "property name",
            "property data type",
            "unit of measure dimension code",
        ],
        [
            ["p1", "gizmo rated flow", "Number", "VOLFLO"],
            ["p2", "gizmo casing material", "Text", ""],
        ],
    )
    return rule_box_fields.Cfihos(tmp_path)


def test_cfihos_classes_are_found_by_name_with_their_children_and_properties(tmp_path):
    cf = _cfihos(tmp_path)
    assert cf.classes_for("invented gizmo") == [
        "invented gizmo",
        "small invented gizmo",
    ]
    assert (
        cf.properties_for("invented gizmo")
        == ["gizmo casing material", "gizmo rated flow"]
        or cf.properties_for("invented gizmo")[0] == "gizmo rated flow"
    )
    assert cf.properties_for("unknown thing") == []


GOOD_FIELDS = {
    "fields": [
        {
            "role": "rated_flow",
            "kind": "flow",
            "label": "Rated flow",
            "cfihos_property": "gizmo rated flow",
        },
        {
            "role": "casing_material",
            "kind": "text",
            "label": "Casing material",
            "cfihos_property": "made up property",
        },
        {
            "role": "design_pressure",
            "kind": "pressure",
            "label": "Design pressure",
            "cfihos_property": None,
        },
    ]
}


def test_a_field_list_keeps_only_fields_of_the_right_shape_and_only_real_cfihos_names():
    good, why = rule_box_fields.verify(json.dumps(GOOD_FIELDS), {"gizmo rated flow"})
    assert why is None and [f["role"] for f in good] == [
        "rated_flow",
        "casing_material",
        "design_pressure",
    ]
    assert (
        good[1]["cfihos_property"] is None
        and good[0]["cfihos_property"] == "gizmo rated flow"
    )
    bad = {
        "fields": [
            *GOOD_FIELDS["fields"][:1],
            {
                "role": "Bad Role",
                "kind": "flow",
                "label": "x y",
                "cfihos_property": None,
            },
            {
                "role": "rated_flow",
                "kind": "flow",
                "label": "Duplicate",
                "cfihos_property": None,
            },
            {
                "role": "other_thing",
                "kind": "banana",
                "label": "Other",
                "cfihos_property": None,
            },
        ]
    }
    assert rule_box_fields.verify(json.dumps(bad), set()) == (
        None,
        "too_few_good_fields",
    )
    assert rule_box_fields.verify("nope", set()) == (None, "reply_not_json")


def test_field_lists_are_built_only_for_types_without_an_approved_list_and_are_marked_to_confirm(
    rules, tmp_path
):
    with rules:
        for rid, eq in (
            ("r1", "invented gizmo"),
            ("r2", "pressure vessel"),
            ("r3", "general"),
        ):
            rules.execute(
                f"INSERT INTO {rule_box_labels_table()} VALUES (?,?,?,'a',NULL,'h','v','t',NULL)",
                (rid, "datasheet", eq),
            )
    rule_box_fields.ensure_schema(rules)
    cf = _cfihos(tmp_path)
    assert rule_box_fields.types_without_a_list(rules) == ["invented gizmo"]
    jobs, members, counts = rule_box_fields.jobs(rules, cf, _gate_open)
    assert counts == {"types_to_build": 1, "types_with_no_cfihos_class": 0}
    assert (
        "gizmo rated flow" in jobs[0].prompt
        and Q_NUM in jobs[0].prompt
        and jobs[0].docs == {DOC}
    )
    apply = rule_box_fields.storer(rules, members, "claude-sonnet-5-5")
    report = rule_box_run.run(
        jobs,
        model="claude-sonnet-5-5",
        step_prefix="f",
        version="v",
        apply=apply,
        send=Fake(lambda p: json.dumps(GOOD_FIELDS)),
    )
    assert report["stored"] == 1 and apply.tally["fields_stored"] == 3
    states = {r[0] for r in rules.execute(f"SELECT state FROM {rule_box_fields.TABLE}")}
    assert states == {"field list: AI-built, to confirm"}
    assert rule_box_check.fields_for("invented gizmo") is None
    assert rule_box_check.fields_for("invented gizmo", rules) == {
        "casing_material": "text",
        "design_pressure": "pressure",
        "rated_flow": "flow",
    }
    assert (
        rule_box_check.field_list_state("invented gizmo")
        == "field list: AI-built, to confirm"
    )
    assert (
        rule_box_check.field_list_state("pressure vessel")
        == rule_box_fields.FIXED_STATE
    )
    assert rule_box_fields.types_without_a_list(rules) == []
    out = tmp_path / "lists.json"
    assert rule_box_fields.export(rules, out) == 1
    assert (
        json.loads(out.read_text())["invented gizmo"]["state"]
        == "field list: AI-built, to confirm"
    )


def rule_box_labels_table():
    return rule_boxes.TABLE


def test_a_standard_past_the_family_list_only_by_the_owners_file_and_still_needs_role_and_approval(
    rules, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "standards_compiler_families", "ISO")
    assert cli.make_gate(rules)(DOC, LABEL) == "FamilyNotAllowed"
    (tmp_path / cli.EXCEPTIONS_FILE).write_text(json.dumps({"document_ids": [DOC]}))
    assert cli.make_gate(rules)(DOC, LABEL) is None
    assert cli.make_gate(rules)("other-doc", LABEL) == "FamilyNotAllowed"
    path = __import__("app.claude_approved", fromlist=["x"]).list_path()
    path.write_text(json.dumps({"documents": []}))
    assert cli.make_gate(rules)(DOC, LABEL) == "DocumentNotApproved"


def test_a_relabel_under_a_new_prompt_keeps_the_old_box_and_asks_only_what_is_not_yet_on_the_new_one(
    rules,
):
    with rules:
        rules.execute(
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r1','datasheet','pump','c',NULL,'old','box-label-v1','t',NULL)"
        )
    assert [r["id"] for r in rule_boxes.todo(rules)] == ["r1", "r2", "r3"]
    jobs, members, _c = rule_boxes.jobs(rules, _gate_open, per_prompt=5)
    assert len(jobs) == 1 and rule_boxes.PER_PROMPT == 5
    apply = rule_boxes.storer(rules, members, "m")
    rule_box_run.run(
        jobs,
        model="claude-haiku-4-5",
        step_prefix="s",
        version="v",
        apply=apply,
        send=Fake(_labels),
    )
    row = rules.execute(
        f"SELECT box, box_v1, prompt_version FROM {rule_boxes.TABLE} WHERE rule_id='r1'"
    ).fetchone()
    assert tuple(row) == ("a", "c", rule_boxes.PROMPT_VERSION)
    assert rule_boxes.todo(rules) == []


def test_a_checks_table_made_before_the_field_list_column_is_migrated(rules):
    rules.execute(f"DROP TABLE {rule_box_check.CHECKS}")
    rules.execute(
        f"CREATE TABLE {rule_box_check.CHECKS} (rule_id TEXT PRIMARY KEY, status TEXT NOT NULL)"
    )
    rule_box_check.ensure_schema(rules)
    assert "field_list_state" in [
        r[1] for r in rules.execute(f"PRAGMA table_info({rule_box_check.CHECKS})")
    ]


def test_a_reply_with_a_sentence_before_the_fenced_object_is_still_read():
    text = 'The requirement is about one field.\n```json\n{"field_role": null, "kind": null, "reason": "not_on_the_sheet"}\n```'
    assert rule_box_check._parse_object(text) == {
        "field_role": None,
        "kind": None,
        "reason": "not_on_the_sheet",
    }
    assert rule_box_check._parse_object("no object here {not json") is None
    assert rule_box_check._parse_object('[{"a": 1}]') is None


def test_only_a_rule_with_a_figure_and_a_unit_in_its_own_words_is_asked_and_the_figures_are_in_the_prompt(
    rules,
):
    with rules:
        for rid in ("r1", "r2", "r3"):
            rules.execute(
                f"INSERT INTO {rule_boxes.TABLE} VALUES (?,?,?,?,NULL,'h','v','t',NULL)",
                (rid, "datasheet", "pressure vessel", "a"),
            )
    assert rule_box_check.has_figure(
        _row(rules, "r1")
    ) and not rule_box_check.has_figure(_row(rules, "r2"))
    assert rule_box_check.figures_of(_row(rules, "r1")) == [("10", "bar")]
    assert [r["id"] for r in rule_box_check.check_todo(rules)] == [
        "r1",
        "r2",
    ]  # r2 is a list rule
    assert rule_box_check.todo_by_type(rules) == {"pressure vessel": 2}
    prompt = rule_box_check.check_prompt(
        _row(rules, "r1"), LABEL, "pressure vessel", FIELDS
    )
    assert "FIGURES AND UNITS CODE FOUND IN IT: 10 bar" in prompt
    assert "FIGURES AND UNITS" not in rule_box_check.check_prompt(
        _row(rules, "r2"), LABEL, "pressure vessel", FIELDS
    )
    counts = rule_box_check.settle_without_a_call(rules)
    assert counts["not_decidable_from_a_datasheet"] == 1
    rows = dict(
        rules.execute(
            f"SELECT rule_id, reason FROM {rule_box_check.CHECKS} WHERE status = 'no typed check'"
        ).fetchall()
    )
    assert rows == {"r3": "not_decidable_from_a_datasheet"}


# ------------------------------------------------------------------------------------------ scope and identity
def _scoped_row(**over):
    row = {
        "quote": Q_NUM,
        "applies_to": "pressure vessels",
        "condition_text": None,
        "exception_text": None,
    }
    row.update(over)
    return row


@pytest.mark.parametrize(
    "over, reason",
    [
        ({"condition_text": "for gas service"}, "condition"),
        ({"exception_text": "unless the vessel is jacketed"}, "exception"),
        (
            {"quote": "The design pressure shall be 10 bar only for hydrogen."},
            "condition_word_in_the_rule",
        ),
        ({"applies_to": "stainless steel pressure vessels"}, "applies_to_narrows"),
        ({"applies_to": "jacketed vessels"}, "applies_to_narrows"),
    ],
)
def test_a_rule_narrowed_by_anything_is_scoped_and_keeps_its_scope_text(over, reason):
    said = rule_box_scope.scope_problem(_scoped_row(**over), "pressure vessel")
    assert said is not None and said[0] == reason


def test_a_rule_with_no_narrowing_beyond_the_equipment_type_is_not_scoped():
    assert rule_box_scope.scope_problem(_scoped_row(), "pressure vessel") is None
    assert (
        rule_box_scope.scope_problem(
            _scoped_row(applies_to="all the pressure vessels of this standard"),
            "pressure vessel",
        )
        is None
    )


def test_the_subject_must_be_the_quantity_of_the_field_by_the_pairing_rule():
    assert rule_box_scope.subject_matches(
        "design pressure", "design pressure", "pressure vessel"
    )
    assert rule_box_scope.subject_matches(
        "the design pressure of the vessel", "design pressure", "pressure vessel"
    )
    assert not rule_box_scope.subject_matches(
        "coating thickness", "corrosion allowance", "pressure vessel"
    )
    assert not rule_box_scope.subject_matches("", "design pressure", "pressure vessel")


def test_a_check_whose_subject_is_not_the_fields_quantity_is_a_failed_check(rules):
    row = _row(rules, "r1")
    wrong = _good_number(subject="design pressure", field_role="test_pressure")
    assert (
        rule_box_check.verify_check(row, wrong, FIELDS)[1]
        == "subject_differs_from_field"
    )
    assert (
        rule_box_check.verify_check(row, _good_number(subject="made up words"), FIELDS)[
            1
        ]
        == "subject_not_in_rule"
    )
    assert (
        rule_box_check.verify_check(row, _good_number(subject=""), FIELDS)[1]
        == "subject_not_in_rule"
    )


def test_a_stored_check_that_is_narrowed_is_moved_to_scoped_and_a_scoped_rule_is_never_asked(
    rules,
):
    with rules:
        rules.execute(
            "UPDATE compiled_rules SET exception_text = 'unless jacketed' WHERE id = 'r1'"
        )
        rules.execute(
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r1','datasheet','pressure vessel','a',NULL,'h','v','t',NULL)"
        )
    assert rule_box_check.check_todo(rules) == []
    assert (
        rule_box_check.settle_without_a_call(rules)["scoped: judge at review time"] == 1
    )
    row = rules.execute(
        f"SELECT status, reason, scope_text FROM {rule_box_check.CHECKS}"
    ).fetchone()
    assert tuple(row) == (
        "scoped: judge at review time",
        "exception",
        "unless jacketed",
    )
    rules.execute(f"UPDATE {rule_box_check.CHECKS} SET status = 'checked'")
    assert rule_box_check.apply_scope_gate(rules) == 1


def test_only_a_same_quantity_requirement_on_the_equipment_advances_after_the_fresh_model(
    rules,
):
    with rules:
        rules.execute(
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r1','datasheet','pressure vessel','a',NULL,'h','v','t',NULL)"
        )
    jobs, members, _c = rule_box_check.check_jobs(rules, _gate_open)
    rule_box_run.run(
        jobs,
        model="claude-sonnet-5-5",
        step_prefix="c",
        version="v",
        apply=rule_box_check.check_storer(rules, members, "claude-sonnet-5-5"),
        send=Fake(lambda p: json.dumps(_good_number())),
    )
    jobs, members, _c = rule_box_check.second_jobs(
        rules, _gate_open, "claude-haiku-5-5"
    )
    answer = json.dumps(
        {"box": "a", "field_role": "design_pressure", "limit": "10", "unit": "bar"}
    )
    rule_box_run.run(
        jobs,
        model="claude-haiku-5-5",
        step_prefix="s",
        version="v",
        apply=rule_box_check.second_storer(rules, members, "claude-haiku-5-5"),
        send=Fake(lambda p: answer),
    )
    assert rule_box_check.advanced(rules) == 0
    rule_box_scope.ensure_schema(rules)
    for relation, requirement, expected in (
        ("narrower", "yes", 0),
        ("same", "no", 0),
        ("same", "yes", 1),
    ):
        rules.execute(f"DELETE FROM {rule_box_scope.IDENTITY}")
        jobs, members, counts = rule_box_scope.identity_jobs(
            rules, _gate_open, "claude-haiku-5-5", {DOC: LABEL}
        )
        assert (
            counts["prompts"] == 1
            and "design pressure" in jobs[0].prompt
            and "10 bar" in jobs[0].prompt
        )
        apply = rule_box_scope.identity_storer(
            rules, members, "claude-haiku-5-5", rule_box_check._parse_object
        )
        reply = json.dumps(
            {"relation": relation, "requirement_on_the_equipment": requirement}
        )
        rule_box_run.run(
            jobs,
            model="claude-haiku-5-5",
            step_prefix="i",
            version="v",
            apply=apply,
            send=Fake(lambda p, reply=reply: reply),
        )
        assert rule_box_check.advanced(rules) == expected
    assert (
        rule_box_scope.identity_jobs(rules, _gate_open, "claude-sonnet-5-5", {})[2][
            "prompts"
        ]
        == 0
    )


# ------------------------------------------------------------------------------------------ step 8: the judge
PAGE_TEXT = {
    1: "Invented datasheet. The set pressure is 12 bar and the body is cast iron with a painted finish."
}
QUOTES_BY_SHOWN = {
    1: "The set pressure is 12 bar and the body",
    2: "body is cast iron with a painted finish",
}
RULE_TEXT = "The set pressure of the invented valve shall be marked on the body."


def _rec(
    i,
    verdict,
    page=1,
    quote="The set pressure is 12 bar and the body is cast iron",
    scope=None,
    can="yes",
):
    return {
        "i": i,
        "verdict": verdict,
        "scope_applies": scope,
        "page": page,
        "quote": quote,
        "reason": "the sheet states the set pressure",
        "document_can_state": can,
    }


def _v(rec, scoped=False, rule=RULE_TEXT):
    return rule_box_judge.verified(rec, 1, PAGE_TEXT, scoped, rule)


def test_a_record_stands_only_when_its_quote_is_on_the_cited_page_and_touches_the_rule():
    ok = _v(_rec(1, "fail"))
    assert ok["evidence_ok"] and ok["page"] == 1
    for bad in (
        _rec(1, "fail", quote="The set pressure is 99 bar and nothing else"),
        _rec(1, "fail", page=2),
    ):
        got = _v(bad)
        assert got["evidence_ok"] is False and got["quote"] is None
    adjacent = _v(
        _rec(1, "query", quote="Invented datasheet. The set"),
        rule="The relief valve capacity certificate shall be supplied.",
    )
    assert adjacent["on_page"] and adjacent["evidence_ok"] is False
    assert _v(_rec(2, "fail")) is None
    assert _v(_rec(1, "maybe")) is None
    assert _v(_rec(1, "fail", can="perhaps")) is None
    assert _v(_rec(1, "fail", scope="perhaps"), scoped=True) is None


def test_two_readings_must_agree_and_carry_verified_evidence_or_the_rule_goes_to_the_engineer():
    fail, other = _v(_rec(1, "fail")), _v(_rec(1, "query"))
    nowhere = _v(_rec(1, "fail", quote="not on any page at all here"))
    assert rule_box_judge.combine(fail, fail, False)[0] == "needs engineer"
    assert rule_box_judge.combine(fail, other, False)[0] == "needs engineer"
    assert rule_box_judge.combine(fail, nowhere, False)[0] == "needs engineer"
    assert rule_box_judge.combine(fail, None, False)[0] == "needs engineer"
    passing = _v(
        _rec(1, "pass", quote="The body is cast iron with a painted finish"),
        rule="The valve body shall be cast iron.",
    )
    assert rule_box_judge.combine(passing, passing, False)[0] == "needs engineer"
    unproved = _v(_rec(1, "pass", quote="invented words not present"))
    assert rule_box_judge.combine(unproved, unproved, False)[0] == "needs engineer"
    adjacent = _v(
        _rec(1, "query", quote="Invented datasheet. The set"),
        rule="The relief valve capacity certificate shall be supplied.",
    )
    assert (
        rule_box_judge.combine(adjacent, adjacent, False)[1]
        == "the quoted words do not touch the rule's subject"
    )


def test_a_rule_a_document_kind_cannot_state_is_not_applicable_only_when_both_readings_say_so():
    no = _v(_rec(1, "query", can="no"))
    yes = _v(_rec(1, "query"))
    assert rule_box_judge.combine(no, no, False) == (
        "not applicable",
        "the sheet states the set pressure",
        None,
    )
    assert rule_box_judge.combine(no, yes, False)[0] == "needs engineer"


def test_a_scoped_rule_needs_both_readings_to_say_the_scope_applies():
    yes, no, unsure = (
        _v(_rec(1, "fail", scope=x), scoped=True) for x in ("yes", "no", "unsure")
    )
    assert rule_box_judge.combine(yes, yes, True)[0] == "needs engineer"
    assert rule_box_judge.combine(no, no, True)[0] == "not applicable"
    assert rule_box_judge.combine(yes, no, True)[0] == "needs engineer"
    assert rule_box_judge.combine(unsure, unsure, True)[0] == "needs engineer"


def test_a_cut_off_rule_is_never_sent_and_near_duplicates_are_one_unit():
    assert rule_box_judge.is_incomplete("The following limits shall apply:")
    assert rule_box_judge.is_incomplete("The valve shall be marked and")
    assert not rule_box_judge.is_incomplete("The valve shall be marked.")
    rows = [
        {
            "id": "a",
            "standard_document_id": "s",
            "clause": "1.1",
            "quote": "Mark every invented valve on its body plainly 2024.",
            "status": "stored by kind",
            "scope_text": None,
        },
        {
            "id": "b",
            "standard_document_id": "s",
            "clause": "2.7",
            "quote": "Mark every invented valve on its body, plainly 2019.",
            "status": "stored by kind",
            "scope_text": None,
        },
        {
            "id": "c",
            "standard_document_id": "s",
            "clause": "3",
            "quote": "Limits shall apply:",
            "status": "stored by kind",
            "scope_text": None,
        },
    ]
    units, incomplete, merged = rule_box_judge.prepare(rows)
    assert len(units) == 1 and [m["clause"] for m in units[0]["members"]] == [
        "1.1",
        "2.7",
    ]
    assert [r["id"] for r in incomplete] == ["c"] and len(merged) == 1
    assert (
        rule_box_judge.clauses_of(units[0], {"s": "STD-1"})
        == "STD-1 clause 1.1; STD-1 clause 2.7"
    )


def _setup_judge(rules):
    with rules:
        rules.execute("DROP TABLE IF EXISTS rule_box_labels")
    rule_boxes.ensure_schema(rules)
    rule_box_check.ensure_schema(rules)
    rule_box_judge.ensure_schema(rules)
    _document("sub-1", "SUB-1", pages=(PAGE_TEXT[1],))
    with rules:
        for rid, status in (
            ("r3", "stored by kind"),
            ("r1", "scoped: judge at review time"),
        ):
            rules.execute(
                f"INSERT INTO {rule_boxes.TABLE} VALUES (?,?,?,?,NULL,'h','v','t',NULL)",
                (rid, "datasheet", "general", "b"),
            )
            rules.execute(
                f"INSERT INTO {rule_box_check.CHECKS} (rule_id, status, scope_text, created_at) VALUES (?,?,?,'t')",
                (rid, status, "for jacketed vessels" if rid == "r1" else None),
            )
        rules.execute(
            "UPDATE compiled_rules SET quote = 'The set pressure of the invented valve and the body finish shall be marked on the body.' WHERE id IN ('r1','r3')"
        )


def test_the_judge_asks_each_rule_twice_independently_and_writes_labelled_rows_with_page_and_comment(
    rules, tmp_path
):
    _setup_judge(rules)
    rows = rule_box_judge.relevant_rules(rules, "sub-1")
    assert {r["id"] for r in rows} == {"r1", "r3"}
    units, incomplete, _merged = rule_box_judge.prepare(rows)
    assert len(units) == 2 and incomplete == []
    pages = rule_box_judge.pages_of(rules, "sub-1")
    jobs, members = rule_box_judge.build_jobs("sub-1", units, {DOC: LABEL}, pages)
    assert (
        len(jobs) == 2
        and jobs[0].prompt != jobs[1].prompt
        and "independent second reading" in jobs[1].prompt
    )
    assert (
        "for jacketed vessels" in jobs[0].prompt
        and "ONE submitted datasheet" in jobs[0].prompt
    )

    def reply(prompt):
        out = []
        for n in range(1, 3):
            out.append(
                _rec(
                    n,
                    "query",
                    scope="yes" if "jacketed" in prompt else None,
                    quote=QUOTES_BY_SHOWN[n],
                )
            )
        return json.dumps(out)

    apply = rule_box_judge.make_storer(
        rules, "sub-1", pages, "m", members, {DOC: LABEL}
    )
    report = rule_box_run.run(
        jobs,
        model="claude-sonnet-5-5",
        step_prefix="j",
        version="v",
        apply=apply,
        send=Fake(reply),
    )
    apply.flush()
    assert report["asked"] == 2
    got = rules.execute(
        f"SELECT status, label, page FROM {rule_box_judge.JUDGED} ORDER BY rule_id"
    ).fetchall()
    assert [tuple(g) for g in got] == [
        ("Query", "AI judgement, engineer to confirm", 1)
    ] * 2
    assert rule_box_judge.relevant_rules(rules, "sub-1") == []
    out = tmp_path / "crs.xlsx"
    assert rule_box_judge.export_crs(rules, "sub-1", out) == 2
    import openpyxl

    sheet = openpyxl.load_workbook(out)["CRS"]
    rows_out = list(sheet.iter_rows(min_row=2, values_only=True))
    assert [r[0] for r in rows_out] == [1, 2] and all(
        r[2] == 1 and r[4].startswith("The datasheet states") for r in rows_out
    )
    assert all("engineer to confirm" not in r[4] for r in rows_out)


def test_the_export_refuses_a_row_with_no_page_or_comment(rules, tmp_path):
    _setup_judge(rules)
    rule_box_judge.ensure_schema(rules)
    rules.execute(
        f"INSERT INTO {rule_box_judge.JUDGED} (document_id, rule_id, status, clause, rule_quote, calls_json, label, model, prompt_version, created_at)"
        " VALUES ('sub-1','r1','Query','9.9','x','[]','l','m','v','t')"
    )
    with pytest.raises(rule_box_judge.RowRefused):
        rule_box_judge.export_crs(rules, "sub-1", tmp_path / "x.xlsx")


def test_a_pass_needs_an_affirmative_quote_with_the_value_the_rule_asks_for():
    pp = rule_box_judge.pass_problem
    assert (
        pp("The edition shall be the latest unless stated otherwise.", "Edition 2019")
        == "silence"
    )
    assert (
        pp("The pressure shall be marked in bar.", "Pressure: not stated")
        == "not_affirmative"
    )
    assert (
        pp(
            "The design pressure shall not exceed 10 bar.",
            "Design pressure see drawing",
        )
        == "no_value"
    )
    assert pp("The sheet shall be in English.", "Rated flow 12 m3/h") == "no_value"
    assert pp("The sheet shall be in English.", "Language: English") is None
    assert pp("The valve shall be marked.", "Marked on the body plate") is None
    stated = _v(
        _rec(1, "pass", quote="The set pressure is 12 bar and the body is cast iron"),
        rule="The set pressure shall be at most 14 bar.",
    )
    assert stated["pass_problem"] is None
    nothing = _v(
        _rec(1, "pass", quote="Invented datasheet. The set pressure is"),
        rule="The set pressure shall be at most 14 bar.",
    )
    assert rule_box_judge.combine(nothing, nothing, False)[0] == "needs engineer"
    silent = _v(
        _rec(1, "pass"),
        rule="The set pressure shall be stated unless stated otherwise.",
    )
    assert rule_box_judge.combine(silent, silent, False)[0] == "not applicable"


def test_edition_rules_make_no_call_and_a_not_applicable_reason_is_the_models_own_words_without_new_numbers():
    rows = [
        {
            "id": "e",
            "standard_document_id": "s",
            "clause": "1",
            "quote": "The latest edition of the standard shall apply.",
            "status": "stored by kind",
            "scope_text": None,
        }
    ]
    units, unsent, _m = rule_box_judge.prepare(rows)
    assert (
        units == []
        and len(unsent) == 1
        and rule_box_judge.is_edition_rule(rows[0]["quote"])
    )
    assert (
        rule_box_judge.clean_reason("About site delivery media, not the sheet", "rule")
        == "About site delivery media, not the sheet"
    )
    assert rule_box_judge.clean_reason("Concerns the 2019 code", "rule text") == ""
    no = _v(_rec(1, "query", can="no") | {"reason": "site delivery media only"})
    assert rule_box_judge.combine(no, no, False)[1] == "site delivery media only"


def test_the_export_keeps_needs_engineer_rows_and_the_label_off_the_contractor_workbook(
    rules, tmp_path
):
    _setup_judge(rules)
    rules.execute(
        f"INSERT INTO {rule_box_judge.JUDGED} (document_id, rule_id, status, reason, page, clause, rule_quote, calls_json, label, model, prompt_version, created_at)"
        " VALUES ('sub-1','r1','needs engineer','the two readings differ',2,'STD-1 clause 4.2','x','[]','AI judgement, engineer to confirm','m','v','t')"
    )
    rules.execute(
        f"INSERT INTO {rule_box_judge.JUDGED} (document_id, rule_id, status, page, evidence, clause, rule_quote, calls_json, label, model, prompt_version, created_at)"
        " VALUES ('sub-1','r3','Query',1,'The set pressure is 12 bar','STD-1 clause 4.3','The set pressure shall be stated.','[{\"reason\": \"the sheet gives a set pressure\"}]','AI judgement, engineer to confirm','m','v','t')"
    )
    out = tmp_path / "contractor.xlsx"
    assert rule_box_judge.export_crs(rules, "sub-1", out) == 1
    import re
    import zipfile

    import openpyxl

    book = openpyxl.load_workbook(out)
    assert book.sheetnames == ["CRS"]
    cells = [
        str(c)
        for row in book["CRS"].iter_rows(values_only=True)
        for c in row
        if c is not None
    ]
    assert len(book["CRS"][1]) == 6 and len(cells) >= 6
    banned = re.compile(r"engineer|\bAI\b|judgement|internal", re.IGNORECASE)
    assert [c for c in cells if banned.search(c)] == []
    with zipfile.ZipFile(out) as z:
        for name in z.namelist():
            assert not banned.search(z.read(name).decode("utf-8", "ignore")), name
    inner = openpyxl.load_workbook(tmp_path / "contractor-internal.xlsx")
    line = next(
        inner["AI judgement not decided"].iter_rows(min_row=2, values_only=True)
    )
    assert (
        line[2] == 2
        and "disagreed" in line[3]
        and "Check STD-1 clause 4.2" in line[3]
        and "readings differ" not in line[3]
    )
    assert line[5].startswith("Internal:")
    assert (
        rule_box_judge.clause_label(
            {"standard_document_id": "s", "clause": "6.1"}, {"s": "SAES-A-022.pdf"}
        )
        == "SAES-A-022 clause 6.1"
    )


def test_a_quote_already_used_for_another_rule_is_not_evidence_twice(rules):
    _setup_judge(rules)
    pages = rule_box_judge.pages_of(rules, "sub-1")
    units, _i, _m = rule_box_judge.prepare(
        rule_box_judge.relevant_rules(rules, "sub-1")
    )
    units[1]["rep"] = {
        **dict(units[1]["rep"]),
        "quote": "The set pressure of the other invented valve shall be marked on its body.",
    }
    units[1]["members"] = [units[1]["rep"]]
    jobs, members = rule_box_judge.build_jobs("sub-1", units, {DOC: LABEL}, pages)
    apply = rule_box_judge.make_storer(
        rules, "sub-1", pages, "m", members, {DOC: LABEL}
    )
    rule_box_run.run(
        jobs,
        model="claude-sonnet-5-5",
        step_prefix="j",
        version="v",
        apply=apply,
        send=Fake(
            lambda p: json.dumps([_rec(n, "query", scope="yes") for n in (1, 2)])
        ),
    )
    apply.flush()
    statuses = sorted(
        r[0] for r in rules.execute(f"SELECT status FROM {rule_box_judge.JUDGED}")
    )
    assert statuses == ["Query", "needs engineer"]


# ------------------------------------------------------------------------------------------ routing and scope in the prompts
def test_only_datasheet_and_any_rules_go_to_datasheet_checks_and_a_standard_rule_only_by_a_code_rule(
    rules,
):
    fields = FIELDS
    row = lambda kind, quote: {"document_kind": kind, "quote": quote}  # noqa: E731
    elig = rule_box_check.eligible_for_datasheet
    assert elig(row("datasheet", "x"), "pressure vessel", fields) and elig(
        row("any", "x"), "pressure vessel", fields
    )
    for kind in ("procedure", "drawing", "specification", "report", "study"):
        assert not elig(
            row(kind, "The design pressure shall be marked."), "pressure vessel", fields
        )
    assert elig(
        row("standard", "The design pressure shall not exceed 10 bar."),
        "pressure vessel",
        fields,
    )
    assert not elig(
        row("standard", "The inspector shall keep records of every visit."),
        "pressure vessel",
        fields,
    )


def test_a_rule_of_another_document_kind_is_stored_for_that_kind_and_not_asked(rules):
    with rules:
        rules.execute(
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r1','procedure','pressure vessel','a',NULL,'h','v','t',NULL)"
        )
        rules.execute(
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r3','datasheet','pressure vessel','a',NULL,'h','v','t',NULL)"
        )
        rules.execute(
            "UPDATE compiled_rules SET quote = 'The test pressure shall be at least 15 bar.' WHERE id = 'r3'"
        )
    assert [r["id"] for r in rule_box_check.check_todo(rules)] == ["r3"]
    counts = rule_box_check.settle_without_a_call(rules)
    assert counts["stored for review of that kind"] == 1
    row = rules.execute(
        f"SELECT status, reason FROM {rule_box_check.CHECKS} WHERE rule_id = 'r1'"
    ).fetchone()
    assert tuple(row) == ("stored for review of that kind", "procedure")


def test_a_list_rule_without_a_figure_is_sent_and_a_plain_obligation_is_not():
    assert rule_box_check.is_list_rule(
        "The body material shall be carbon steel or stainless steel."
    )
    assert rule_box_check.is_list_rule("Flange rating shall be class 300 or higher.")
    assert not rule_box_check.is_list_rule("The valve shall be marked legibly.")


def test_the_prompts_carry_the_rules_scope_and_a_dropped_condition_is_a_failed_check(
    rules,
):
    with rules:
        rules.execute(
            "UPDATE compiled_rules SET applies_to = 'jacketed vessels', exception_text = 'unless lined', condition_text = 'for gas' WHERE id = 'r1'"
        )
    row = {**dict(_row(rules, "r1")), "equipment_type": "pressure vessel"}
    prompt = rule_box_check.check_prompt(row, LABEL, "pressure vessel", FIELDS)
    assert (
        "APPLIES TO: jacketed vessels" in prompt
        and "ITS EXCEPTION: unless lined" in prompt
        and "ITS CONDITION: for gas" in prompt
    )
    second = rule_box_check.second_prompt(row, LABEL, "pressure vessel", FIELDS)
    assert (
        "APPLIES TO: jacketed vessels" in second
        and "ITS EXCEPTION: unless lined" in second
        and "ITS CONDITION: for gas" in second
    )
    assert (
        rule_box_check.verify_check(
            row, _good_number(scope="jacketed vessels"), FIELDS
        )[1]
        == "condition_dropped"
    )


def test_every_typed_check_is_exported_for_audit_and_the_denominator_counts_the_rules_that_apply(
    rules, tmp_path
):
    with rules:
        for rid, kind in (("r1", "datasheet"), ("r3", "procedure")):
            rules.execute(
                f"INSERT INTO {rule_boxes.TABLE} VALUES (?,?, 'pressure vessel','a',NULL,'h','v','t',NULL)",
                (rid, kind),
            )
    jobs, members, _c = rule_box_check.check_jobs(rules, _gate_open)
    rule_box_run.run(
        jobs,
        model="claude-sonnet-5-5",
        step_prefix="c",
        version="v",
        apply=rule_box_check.check_storer(rules, members, "claude-sonnet-5-5"),
        send=Fake(lambda p: json.dumps(_good_number())),
    )
    path = tmp_path / "run" / "checks.json"
    assert rule_box_check.export_checks(rules, path) == 1
    saved = json.loads(path.read_text())[0]
    assert (
        saved["rule_id"] == "r1"
        and saved["status"] == "checked"
        and saved["rule_quote"] == Q_NUM
        and saved["field_role"] == "design_pressure"
    )
    assert rule_box_check.denominators(rules) == {
        "pressure vessel": {"apply_to_datasheets": 1, "decided": 0}
    }


# ------------------------------------------------------------------------------------------ the scoped trial
def _scoped_setup(rules):
    with rules:
        rules.execute(
            "UPDATE compiled_rules SET applies_to = 'jacketed vessels' WHERE id = 'r1'"
        )
        rules.execute(
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r1','datasheet','pressure vessel','a',NULL,'h','v','t',NULL)"
        )
    rule_box_check.ensure_schema(rules)
    assert (
        rule_box_check.settle_without_a_call(rules)["scoped: judge at review time"] == 1
    )


def test_the_trial_asks_a_scoped_rule_with_its_scope_and_the_check_must_carry_the_scope_words(
    rules,
):
    _scoped_setup(rules)
    assert rule_box_check.check_todo(rules) == []
    jobs, _members, _c = rule_box_check.check_jobs(rules, _gate_open, trial=True)
    assert len(jobs) == 1 and "APPLIES TO: jacketed vessels" in jobs[0].prompt
    row = {**dict(_row(rules, "r1")), "equipment_type": "pressure vessel"}
    assert (
        rule_box_check.verify_check(row, _good_number(), FIELDS)[1] == "scope_dropped"
    )
    assert (
        rule_box_check.verify_check(row, _good_number(scope="made up scope"), FIELDS)[1]
        == "scope_dropped"
    )
    check, reason, status = rule_box_check.verify_check(
        row, _good_number(scope="jacketed vessels"), FIELDS
    )
    assert (status, reason, check["scope"]) == ("checked", None, "jacketed vessels")


def test_a_scoped_check_is_never_ai_proven_until_the_scope_question_is_answered(rules):
    _scoped_setup(rules)
    jobs, members, _c = rule_box_check.check_jobs(rules, _gate_open, trial=True)
    apply = rule_box_check.check_storer(rules, members, "claude-sonnet-5-5")
    rule_box_run.run(
        jobs,
        model="claude-sonnet-5-5",
        step_prefix="c",
        version="v",
        apply=apply,
        send=Fake(lambda p: json.dumps(_good_number(scope="jacketed vessels"))),
    )
    saved = rules.execute(
        f"SELECT status, scope_required, scope_question FROM {rule_box_check.CHECKS} WHERE rule_id='r1'"
    ).fetchone()
    assert (
        saved["status"] == "checked"
        and saved["scope_required"] == 1
        and "jacketed vessels" in saved["scope_question"]
    )
    assert rule_box_check.scope_pending(rules) == 1
    jobs2, members2, _ = rule_box_check.second_jobs(
        rules, _gate_open, "claude-haiku-5-5"
    )
    assert "APPLIES TO: jacketed vessels" in jobs2[0].prompt
    rule_box_run.run(
        jobs2,
        model="claude-haiku-5-5",
        step_prefix="s",
        version="v",
        apply=rule_box_check.second_storer(rules, members2, "claude-haiku-5-5"),
        send=Fake(
            lambda p: json.dumps(
                {
                    "box": "a",
                    "field_role": "design_pressure",
                    "limit": "10",
                    "unit": "bar",
                }
            )
        ),
    )
    rule_box_scope.ensure_schema(rules)
    jobs3, members3, _ = rule_box_scope.identity_jobs(
        rules, _gate_open, "claude-haiku-5-5", {DOC: LABEL}
    )
    rule_box_run.run(
        jobs3,
        model="claude-haiku-5-5",
        step_prefix="i",
        version="v",
        apply=rule_box_scope.identity_storer(
            rules, members3, "claude-haiku-5-5", rule_box_check._parse_object
        ),
        send=Fake(
            lambda p: json.dumps(
                {"relation": "same", "requirement_on_the_equipment": "yes"}
            )
        ),
    )
    assert rule_box_check.advanced(rules) == 0


# ------------------------------------------------------------------------------------------ field-first linking
def _ff_setup(rules):
    with rules:
        rules.execute(
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r1','specification','pressure vessel','a',NULL,'h','v','t',NULL)"
        )
        rules.execute(
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r2','datasheet','general','a',NULL,'h','v','t',NULL)"
        )
        rules.execute(
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r3','datasheet','pump','a',NULL,'h','v','t',NULL)"
        )
        rules.execute(
            "UPDATE compiled_rules SET quote = 'The invented design pressure shall be at least 4 bar.' WHERE id = 'r2'"
        )


def test_candidates_for_a_field_are_rules_of_any_kind_that_name_its_quantity_best_kind_first(
    rules,
):
    _ff_setup(rules)
    got = [
        r["id"]
        for r in rule_box_fieldfirst.candidates(
            rules, "pressure vessel", "design_pressure"
        )
    ]
    assert (
        got == ["r2", "r1"]
    )  # a datasheet rule first, then the specification rule; the pump rule is another type
    assert (
        rule_box_fieldfirst.candidates(rules, "pressure vessel", "no_such_field") == []
    )


def test_field_first_asks_one_field_per_prompt_and_code_verifies_each_pick(rules):
    _ff_setup(rules)
    plan = [
        i
        for i in rule_box_fieldfirst.dry_plan(rules, ["pressure vessel"])
        if i["role"] == "design_pressure"
    ]
    jobs, members = rule_box_fieldfirst.jobs(rules, plan, _gate_open)
    assert (
        len(jobs) == 1
        and "design pressure" in jobs[0].prompt
        and Q_NUM in jobs[0].prompt
    )

    def reply(prompt):
        good = {
            "candidate": 2,
            "kind": "number",
            "op": "<=",
            "limit": "10",
            "unit": "bar",
            "values": [],
            "condition": None,
            "scope": None,
            "subject": "design pressure",
            "quote": "shall not exceed 10 bar",
            "pass_case": {"value": "8", "unit": "bar"},
            "fail_case": {"value": "12", "unit": "bar"},
        }
        return json.dumps(
            {
                "picks": [
                    good,
                    {**good, "candidate": 9},
                    {**good, "candidate": 1, "limit": "99"},
                ]
            }
        )

    apply = rule_box_fieldfirst.storer(rules, members, "claude-sonnet-5-5")
    rule_box_run.run(
        jobs,
        model="claude-sonnet-5-5",
        step_prefix="f",
        version="v",
        apply=apply,
        send=Fake(reply),
    )
    states = dict(
        rules.execute(f"SELECT rule_id, status FROM {rule_box_check.CHECKS}").fetchall()
    )
    assert states == {"r1": "checked", "r2": "failed check"}
    assert apply.tally["picks"] == 2


# ------------------------------------------------------------------------------------------ a Pass rests on the compared figure


# ------------------------------------------------------------------------------------------ the comparator, ranges, terms, leaks
PRESS_PAGE = "Invented sheet. {q} More words follow."


def _real(rule, quote, verdict="pass", reason="the sheet states the value clearly"):
    """Both readings give `verdict`, through the real verified() and combine()."""
    pages = {1: PRESS_PAGE.format(q=quote)}
    record = {
        "i": 1,
        "verdict": verdict,
        "scope_applies": None,
        "page": 1,
        "quote": quote,
        "reason": reason,
        "document_can_state": "yes",
    }
    one = rule_box_judge.verified(record, 1, pages, False, rule)
    return rule_box_judge.combine(one, one, False)[0]


def test_the_contractor_comment_is_built_by_code_only_and_leaks_nothing_of_the_models_sentence(
    rules, tmp_path
):
    _setup_judge(rules)
    leaky = json.dumps(
        [
            {
                "verdict": "query",
                "reason": "Engineer should confirm this judgement. The AI says fine.",
            }
        ]
    )
    for rid, status in (("r1", "Query"), ("r3", "Query")):
        rules.execute(
            f"INSERT INTO {rule_box_judge.JUDGED} (document_id, rule_id, status, reason, page, evidence, clause, rule_quote, calls_json, label, model, prompt_version, created_at)"
            " VALUES ('sub-1',?,?,?,1,'The set pressure is 12 bar','STD-1 clause 4.3','The set pressure shall be stated.',?,'AI judgement, engineer to confirm','m','v','t')",
            (
                rid,
                status,
                "the code could not compare the stated value with the rule's figure",
                leaky,
            ),
        )
    out = tmp_path / "c.xlsx"
    assert rule_box_judge.export_crs(rules, "sub-1", out) == 2
    import re
    import zipfile

    import openpyxl

    banned = re.compile(
        r"engineer|\bAI\b|judgement|internal|the code|could not compare", re.IGNORECASE
    )
    sheet = openpyxl.load_workbook(out)["CRS"]
    comments = [r[4] for r in sheet.iter_rows(min_row=2, values_only=True)]
    assert comments and not [c for c in comments if banned.search(c)]
    assert all(
        c.startswith("The datasheet states") and c.endswith("revise if not.")
        for c in comments
    )
    with zipfile.ZipFile(out) as z:
        assert not [
            n
            for n in z.namelist()
            if banned.search(z.read(n).decode("utf-8", "ignore"))
        ]
    notes = openpyxl.load_workbook(tmp_path / "c-internal.xlsx")["AI notes"]
    assert "Engineer should confirm" in str(list(notes.iter_rows(values_only=True)))


# ------------------------------------------------------------------------------------------ the judge makes no Pass and no Fail
ATTACKS = [
    ("The design pressure shall not be more than 10 bar.", "Design pressure 15 bar"),
    ("The design pressure shall not be less than 10 bar.", "Design pressure 5 bar"),
    ("The design pressure is not to be less than 10 bar.", "Design pressure 5 bar"),
    ("The design pressure shall not be lower than 10 bar.", "Design pressure 5 bar"),
    ("The design pressure shall not be greater than 10 bar.", "Design pressure 15 bar"),
    (
        "The design pressure shall be not more than 10 bar.",
        "Design pressure 8 +/- 5 bar",
    ),
    ("The design pressure shall be not more than 10 bar.", "Design pressure 8 ±5 bar"),
    (
        "The design pressure shall be not more than 10 bar.",
        "Design pressure 8 bar -2/+5",
    ),
    (
        "The design pressure shall be not more than 2000 bar.",
        "Design pressure 1 000 bar",
    ),
    ("The valve body shall be carbon steel.", "Valve body: low carbon steel"),
    (
        "The valve body shall be stainless steel.",
        "Valve body: carbon steel (stainless steel optional)",
    ),
    (
        "The valve body shall be stainless steel.",
        "Valve body: stainless steel replaced by carbon steel",
    ),
    (
        "The valve body shall be stainless steel.",
        "Valve body: stainless steel unless carbon",
    ),
    (
        "The valve body shall be stainless steel.",
        "Body material: carbon steel Trim material: stainless steel",
    ),
    ("The sheet shall be in English.", "Language: non English"),
    ("The valve shall be fire safe.", "Valve: unsafe fire safe"),
    ("The valve shall be with or without lining.", "Valve: with lining"),
    ("The design pressure shall be not more than 10 bar.", "Design pressure 15 bar"),
    ("The valve body shall be stainless steel.", "Valve body: stainless steel"),
    ("The design pressure shall be not more than 10 bar.", "Design pressure 5 bar"),
]


@pytest.mark.parametrize("rule, quote", ATTACKS)
@pytest.mark.parametrize("verdict", ["pass", "fail", "query"])
def test_no_reading_of_any_rule_and_quote_becomes_a_pass_or_a_fail(
    rule, quote, verdict
):
    assert _real(rule, quote, verdict=verdict) not in ("Pass", "Fail")


def test_where_the_judge_would_have_said_pass_it_keeps_the_verified_quote_for_the_engineer_only():
    rule = "The design pressure shall be not more than 10 bar."
    pages = {1: PRESS_PAGE.format(q="Design pressure 5 bar")}
    record = {
        "i": 1,
        "verdict": "pass",
        "scope_applies": None,
        "page": 1,
        "quote": "Design pressure 5 bar",
        "reason": "the sheet gives it",
        "document_can_state": "yes",
    }
    one = rule_box_judge.verified(record, 1, pages, False, rule)
    status, reason, shown = rule_box_judge.combine(one, one, False)
    assert (status, reason) == ("needs engineer", "the quotes suggest the rule is met")
    assert shown["quote"] == "Design pressure 5 bar" and shown["page"] == 1
    line = rule_box_judge.plain_look(
        {
            "reason": reason,
            "clause": "STD-1 clause 4.2",
            "page": 1,
            "evidence": "Design pressure 5 bar",
        }
    )
    assert (
        "Passage" in line
        and "Design pressure 5 bar" in line
        and "suggests this rule is met" in line
    )


def test_only_a_query_reaches_the_contractor_workbook(rules, tmp_path):
    _setup_judge(rules)
    for rid, status in (("r1", "Pass"), ("r3", "Query")):
        rules.execute(
            f"INSERT INTO {rule_box_judge.JUDGED} (document_id, rule_id, status, page, evidence, clause, rule_quote, calls_json, label, model, prompt_version, created_at)"
            " VALUES ('sub-1',?,?,1,'The set pressure is 12 bar','STD-1 clause 4.3','The set pressure shall be stated.','[]','l','m','v','t')",
            (rid, status),
        )
    assert (
        rule_box_judge.export_crs(rules, "sub-1", tmp_path / "c.xlsx") == 1
    )  # an old Pass row makes no contractor row


_DIRECTION = re.compile(
    r"\b(exceed\w*|below|above|under|over|violat\w*|against|meets?|within|outside|less|more|greater|lower|higher)\b",
    re.I,
)


@pytest.mark.parametrize("rule, quote", ATTACKS)
def test_a_contractor_comment_never_says_which_way_a_value_lies_against_a_limit(
    rule, quote
):
    pages = {1: PRESS_PAGE.format(q=quote)}
    record = {
        "i": 1,
        "verdict": "query",
        "scope_applies": None,
        "page": 1,
        "quote": quote,
        "reason": "the sheet states a value",
        "document_can_state": "yes",
    }
    one = rule_box_judge.verified(record, 1, pages, False, rule)
    status, _reason, shown = rule_box_judge.combine(one, one, False)
    if status != "Query":
        return
    row = {
        "status": status,
        "evidence": shown["quote"],
        "page": shown["page"],
        "clause": "STD-1 clause 4.2",
        "rule_quote": rule,
        "calls_json": "[]",
    }
    comment = rule_box_judge.comment_of(row)
    outside_quotes = re.sub("\u201c[^\u201d]*\u201d", "", comment)
    assert not _DIRECTION.search(outside_quotes), comment
    assert comment.startswith("The datasheet states") and comment.endswith(
        "Contractor to confirm that the stated value complies and revise if not."
    )


@pytest.mark.parametrize(
    "quote",
    [
        "Design pressure NOT 15 bar",
        "Design pressure 15 bar (not applicable)",
        "Design pressure: TBA",
        "Design pressure: 15 bar by others",
    ],
)
def test_a_negation_or_a_placeholder_is_not_a_stated_value_for_a_query(quote):
    rule = "The design pressure shall be stated."
    pages = {1: PRESS_PAGE.format(q=quote)}
    record = {
        "i": 1,
        "verdict": "query",
        "scope_applies": None,
        "page": 1,
        "quote": quote,
        "reason": "the sheet states a value",
        "document_can_state": "yes",
    }
    one = rule_box_judge.verified(record, 1, pages, False, rule)
    assert rule_box_judge.combine(one, one, False)[0] == "needs engineer"
