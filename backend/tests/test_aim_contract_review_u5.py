"""Fresh review of update 5 (19 Nov 2026): the reviewer's tests for blockers B2 and B4 of the contract code checks. Invented values only."""

from app.aim_review import contract_code as K
from app.aim_review import steps as S

BOOKS = {"b": {"identifier": "ZQ-STD-001"}}


def _item(rule_quote: str) -> dict:
    return {"id": "I1", "book": "b", "clause": "4.2", "source": S.HELD, "topic": "t", "rule_quote": rule_quote, "kind": "limit"}  # fmt: skip


def _judged(label: str, quote: str, paper_value, rule_value) -> dict:
    return {"label": label, "quote": quote, "page": 1, "comment": "x", "field": "f",
            "numbers": {"paper_value": paper_value, "rule_value": rule_value}}  # fmt: skip


def test_b2_a_consistent_contract_with_a_long_wrapped_title_gets_no_firm_schedule_line():
    parts = "ABCDEF"

    def title(x: str) -> str:
        if x == "C":
            return "Payment terms including the invoicing procedure and all the taxes that apply here"
        return f"Title words of part {x}"

    listed = "\n".join(f'SCHEDULE "{x}"\n{title(x)}' for x in parts)
    ranked = "\n".join(
        f'{i}.\nSchedule "{x}" and its Attachments' for i, x in enumerate(parts, 1)
    )
    pages = {
        1: "1.1 This Agreement consists of this document and the following attached schedules:\n" + listed
        + "\nA reference to any of the schedules listed above includes its attachments and all documents they name.",
        2: "1.4 In the event of any conflict among the documents the following order of precedence shall govern:\n" + ranked
        + "\nEnd of clause.",
    }  # fmt: skip
    lines = [
        ln
        for ln in K.lines(pages, {"kind": "contract"}, held=set(parts))
        if ln["item_id"] == K.IDS["schedules"]
    ]
    assert not [
        ln["comment"] for ln in lines if ln["label"] == "Not met"
    ]  # every listed Schedule is ranked, every ranked one listed


def test_b4_a_long_defined_terms_comment_is_never_cut_without_the_mark():
    names = [
        "Work",
        "Company",
        "Contractor",
        "Agreement",
        "Services",
        "Materials",
        "Equipment",
        "Personnel",
        "Effective Date",
    ]
    pages = {
        1: " ".join(
            f'the thing here is referred to as the "{n.upper()}".' for n in names
        ),
        2: " ".join(
            f"Then the {n} shall be used as agreed by both sides." for n in names
        ),
    }
    (line,) = [
        ln
        for ln in K.lines(pages, {"kind": "contract"})
        if ln["item_id"] == K.IDS["terms"]
    ]
    whole = line["comment"].rstrip().endswith("confirm the same meaning.")
    assert whole or line["comment"].rstrip().endswith(("…", "[cut]")), line["comment"][
        -60:
    ]  # whole, or cut WITH a visible mark
