"""#805 rule boxes: label, check and second check of compiled rules on a copy. Invented standards text, an injected
transport: nothing leaves."""

from __future__ import annotations

import json
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
from rule_box_tools import rule_box_check, rule_box_run
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
        " condition_text TEXT, exception_text TEXT)"
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
                f"INSERT INTO {rule_boxes.TABLE} VALUES (?,?,?,?,NULL,'m','v','t')",
                (rid, "datasheet", eq, box),
            )
    assert (
        rule_box_check.fields_for("pump")
        and rule_box_check.fields_for("boiler") is None
    )
    counts = rule_box_check.settle_without_a_call(rules)
    assert counts == {"stored by kind": 1, "field list to confirm": 1}
    states = dict(
        rules.execute(f"SELECT rule_id, status FROM {rule_box_check.CHECKS}").fetchall()
    )
    assert states == {"r2": "field list to confirm", "r3": "stored by kind"}
    assert [r["id"] for r in rule_box_check.check_todo(rules)] == ["r1"]


def test_step_two_asks_one_rule_per_prompt_and_stores_the_check_with_the_model(rules):
    with rules:
        rules.execute(
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r1','datasheet','pressure vessel','a',NULL,'h','v','t')"
        )
        rules.execute(
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r3','datasheet','pressure vessel','a',NULL,'h','v','t')"
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
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r1','datasheet','pressure vessel','a',NULL,'h','v','t')"
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
    assert rule_box_check.advanced(rules) == 1
    row = rules.execute(
        f"SELECT agree, model, prompt_version FROM {rule_box_check.SECOND}"
    ).fetchone()
    assert tuple(row) == (1, "claude-haiku-5-5", rule_box_check.SECOND_VERSION)


def test_a_disagreeing_rule_does_not_advance(rules):
    with rules:
        rules.execute(
            f"INSERT INTO {rule_boxes.TABLE} VALUES ('r1','datasheet','pressure vessel','a',NULL,'h','v','t')"
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
