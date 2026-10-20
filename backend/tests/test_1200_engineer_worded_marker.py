"""#1200 follows the engineer's own words through `crs_mapping`: an AI or web
check item an engineer edited carries `engineer_worded`, and the machine-words
scan (`crs_machine_words`) leaves THEIR wording alone; an item they only
confirmed is still the machine's text and is scanned. The scan's own tests
build their rows by hand, so nothing else connects this marker to the rows
`build_crs_rows` really builds.

MUTATION PROOF: M1200-01 (the marker always false: an engineer's own wording
is blocked as machine words) and M1200-02 (always true: a machine-worded
confirmed item passes the gate into the contractor's copy).

Invented data only.
"""

from __future__ import annotations

import pytest

from app import crs_machine_words as mw
from app import crs_mapping, datasheet_checks

CODE = next(k for k in sorted(datasheet_checks.load_rules()["roles"]) if "_" in k)


def _item(origin: str, text: str, **over) -> dict:
    return {
        "id": "ai-1",
        "origin": origin,
        "compliance_status": "NEEDS_ENGINEER_REVIEW",
        "finding": text,
        "confirmed_by": "eng-1",
        "approval_status": "accepted",
        "contractor_page": 2,
        "contractor_section": "Rated power",
        "standard_name": "STD-100.pdf",
        "ai_rationale": "",
        **over,
    }


def _rows(finding: dict) -> list[dict]:
    return crs_mapping.build_crs_rows([finding], [], "inv.pdf")


@pytest.mark.parametrize("origin", ["ai_engineering_check", "web_standard_check"])
def test_an_item_the_engineer_edited_is_marked_and_not_scanned(origin):
    rows = _rows(
        _item(origin, "the model said so", engineer_comment=f"My note on {CODE}.")
    )
    assert [r["engineer_worded"] for r in rows] == [True]
    assert mw.scan_issue_rows(rows) == []


@pytest.mark.parametrize("origin", ["ai_engineering_check", "web_standard_check"])
def test_an_item_the_engineer_only_confirmed_is_machine_text_and_is_scanned(origin):
    rows = _rows(_item(origin, f"The {CODE} is not stated."))
    assert [r["engineer_worded"] for r in rows] == [False]
    [hit] = mw.scan_issue_rows(rows)
    assert hit["cell"] == "comment" and CODE in hit["words"]
