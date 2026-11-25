"""The local model's first valve run (26 Nov 2026): 31 checklist items against Claude's 93, 58 of 61 points "Question", numbers on
5 and none compared. The fixes: the same rule material on every model (read in smaller calls, never cut), the attack per batch
on the local model, and code reading the numbers when unambiguous. Invented rules and papers; no model, no network."""

from __future__ import annotations

from app.aim_review import budget
from app.aim_review import checklist as CL
from app.aim_review import code_numbers as CN
from app.aim_review import material as MT
from app.aim_review import steps as S
from app.aim_review.paper import Paper

RULE = "The corrosion allowance of pressure parts shall be not less than 3 mm."


def _sel(n_rules: int) -> dict:
    pool = [{"book": "b1", "subject": "s", "tagged": True, "page": 1 + k // 10, "clause": f"4.{k}", "id": f"r{k}",
             "source_text": f"Invented rule {k}: the invented value shall be not less than {k} mm. " + "x" * 400,
             "requirement_text": ""} for k in range(n_rules)]  # fmt: skip
    return {"_pool": pool, "books": [{"book": "b1", "alias": "B1", "identifier": "Invented Book", "chosen_subjects": "all"}]}


def test_the_local_model_reads_the_same_rule_material_as_claude_in_smaller_calls():
    sel = _sel(120)
    claude_rows, claude_stats = MT.material(sel, None)
    with budget.using(budget.LOCAL):
        local_rows, local_stats = MT.material(sel, None)
        local_batches = MT._batches(local_rows)
    assert [r["req_id"] for r in local_rows] == [r["req_id"] for r in claude_rows]  # nothing cut
    assert local_stats == claude_stats and len(local_batches) > len(MT._batches(claude_rows)) > 0
    assert all(sum(len(MT._material_line(r)) for r in b) <= budget.LOCAL.batch_chars for b in local_batches)


class _Attack:
    def __init__(self):
        self.calls = []

    def ask(self, **kw):
        self.calls.append(kw)
        return {"remove": [{"id": f"C{len(self.calls):03d}", "why": "invented"}], "fix": [], "add": []}


def test_the_attack_reads_every_batch_on_the_local_model_and_once_on_claude():
    sel = _sel(120)
    made = {"items": [{"id": f"C{k:03d}", "topic": "t", "what_to_check": "w", "book": "B1", "clause": "4.1", "page": 1,
                       "rule_quote": "q", "applies_when": "always", "paper_fields": [], "kind": "limit",
                       "source": "held standard"} for k in range(1, 9)]}  # fmt: skip
    ident = {"kind": "datasheet", "equipment_type": None, "subject": "invented", "service": ""}
    claude = _Attack()
    CL.s3_attack(claude, ident, sel, made, None, "claude-sonnet-5-5")
    local = _Attack()
    with budget.using(budget.LOCAL):
        got = CL.s3_attack(local, ident, sel, made, None, "local")
        n = len(MT._batches(MT.material(sel, None)[0]))
    assert len(claude.calls) == 1 and len(local.calls) == n > 1
    assert len(got["attack"]["removed"]) == n  # every batch's answer counted


def test_code_reads_the_numbers_only_when_the_rule_and_the_quote_hold_one_each():
    assert CN.numbers(RULE, "Corrosion allowance (pressure parts): 1.5 mm") == {
        "paper_value": "1.5", "paper_unit": "mm", "operator": ">=", "rule_value": "3", "rule_unit": "mm"}  # fmt: skip
    assert CN.numbers(RULE, "Corrosion allowance: 1.5 mm shell, 3 mm head") is None  # two values: the judge pairs them
    assert CN.numbers("Values shall be between 3 mm and 6 mm.", "Allowance: 1.5 mm") is None  # no single limit
    assert CN.numbers(RULE, "Design pressure: 20 barg") is None  # another quantity


PAPER = Paper(paper_id="doc_inv_sheet", pages={2: "Invented sheet.\nCorrosion allowance (pressure parts): 1.5 mm\n"})
ITEM = {"id": "C001", "book": "B1", "book_id": "b1", "clause": "6.4", "source": S.HELD, "topic": "corrosion allowance",
        "what_to_check": "corrosion allowance at least the rule's minimum", "rule_quote": RULE, "applies_when": "always",
        "paper_fields": ["Corrosion allowance"], "paper_pages": [2], "kind": "limit"}  # fmt: skip
ANSWER = {"id": "C001", "label": "Question", "field": "Corrosion allowance", "page": 2,
          "quote": "Corrosion allowance (pressure parts): 1.5 mm", "comment": "Please confirm the allowance."}  # fmt: skip


def test_on_the_local_model_a_question_on_a_stated_value_that_breaks_the_rule_is_a_fail_by_code():
    with budget.using(budget.LOCAL):
        line = S._decide(ITEM, dict(ANSWER), PAPER, {}, "")
    assert line["label"] == "Not met" and CN.NOTE in line["code"]
    on_claude = S._decide(ITEM, dict(ANSWER), PAPER, {}, "")
    assert on_claude["label"] == "Question" and CN.NOTE not in (on_claude.get("code") or "")  # Claude: unchanged until scored


def test_a_value_left_open_or_an_unverified_quote_is_never_compared_by_code():
    with budget.using(budget.LOCAL):
        open_ = S._decide(ITEM, {**ANSWER, "deferred": True}, PAPER, {}, "")
        unfound = S._decide(ITEM, {**ANSWER, "quote": "Corrosion allowance: 1.0 mm"}, PAPER, {}, "")
    assert open_["label"] == "Question" and unfound["label"] == "Question"
    assert CN.NOTE not in (open_.get("code") or "") + (unfound.get("code") or "")
